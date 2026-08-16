import importlib.util
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "esp_target", ROOT / "agentic" / "esp_target.py"
)
ESP_TARGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ESP_TARGET)

RTT_SPEC = importlib.util.spec_from_file_location(
    "rtt_reader", ROOT / "agentic" / "rtt_reader.py"
)
RTT_READER = importlib.util.module_from_spec(RTT_SPEC)
RTT_SPEC.loader.exec_module(RTT_READER)


class SerialDetectionTests(unittest.TestCase):
    def target_with_ports(self, ports):
        target = ESP_TARGET.Target.__new__(ESP_TARGET.Target)
        target._list_serial_ports = lambda: ports
        return target

    def test_selects_single_espressif_device(self):
        target = self.target_with_ports([
            ("COM7", 0x303A, "USB JTAG"),
            ("COM2", None, "Bluetooth"),
        ])
        self.assertEqual(target._detect_serial_port(), "COM7")

    def test_rejects_multiple_espressif_devices(self):
        target = self.target_with_ports([
            ("COM7", 0x303A, "USB JTAG"),
            ("COM8", 0x303A, "USB JTAG"),
        ])
        with self.assertRaisesRegex(ESP_TARGET.OpenOCDError, "Multiple"):
            target._detect_serial_port()

    def test_tcl_word_escapes_windows_and_posix_paths(self):
        self.assertEqual(
            ESP_TARGET._tcl_word(r"C:\\Users\\A B\\app.bin"),
            r"C:\\\\Users\\\\A\ B\\\\app.bin",
        )
        self.assertEqual(
            ESP_TARGET._tcl_word("/tmp/a b/app.bin"),
            r"/tmp/a\ b/app.bin",
        )


class ConfigTests(unittest.TestCase):
    def test_supported_board_descriptions_exist(self):
        cli = (ROOT / "bin" / "esp32-agent").read_text(encoding="utf-8")
        names = re.findall(r'\$REPO_DIR/boards/([^"\n]+)', cli)
        self.assertTrue(names)
        for name in names:
            with self.subTest(name=name):
                self.assertTrue((ROOT / "boards" / name).is_file())

    def test_all_project_templates_load(self):
        for path in sorted((ROOT / "templates" / "configs").glob("esp32*.json")):
            with self.subTest(path=path.name), tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                config = tmp_path / "esp_target_config.json"
                config.write_bytes(path.read_bytes())
                chip_name = path.stem
                chip_dir = tmp_path / "chips"
                chip_dir.mkdir()
                (chip_dir / f"{chip_name}.json").write_bytes(
                    (ROOT / "agentic" / "chips" / f"{chip_name}.json").read_bytes()
                )
                loaded = ESP_TARGET.ProjectConfig(config)
                self.assertEqual(loaded.chip.name.lower().replace("-", ""), chip_name)
                self.assertTrue((ROOT / "agentic" / "chips" / f"{chip_name}.svd").is_file())

    def test_supported_svd_files_parse(self):
        for path in sorted((ROOT / "agentic" / "chips").glob("esp32*.svd")):
            with self.subTest(path=path.name):
                ET.parse(path)


class SkillPackagingTests(unittest.TestCase):
    def test_skill_metadata_and_references(self):
        skill_dir = ROOT / "Skills" / "esp32-agent"
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: esp32-agent\n"))
        self.assertIn("\ndescription:", text.split("---", 2)[1])
        for reference in re.findall(r"\(references/([^)]+)\)", text):
            with self.subTest(reference=reference):
                self.assertTrue((skill_dir / "references" / reference).is_file())


class ProcessSafetyTests(unittest.TestCase):
    def test_rtt_reader_process_check_uses_command_line(self):
        result = mock.Mock(returncode=0, stdout=b"python rtt_reader.py --daemonize")
        with mock.patch.object(RTT_READER.subprocess, "run", return_value=result):
            self.assertTrue(RTT_READER._process_is_rtt_reader(123, "linux"))

        result.stdout = b"openocd -f board/esp32c6-builtin.cfg"
        with mock.patch.object(RTT_READER.subprocess, "run", return_value=result):
            self.assertFalse(RTT_READER._process_is_rtt_reader(123, "linux"))

    def test_windows_daemon_precheck_uses_configured_tcl_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "esp_target_config.json"
            config.write_text(
                '{"platform":"windows","openocd":{"tcl_port":7777}}',
                encoding="utf-8",
            )
            output = tmp_path / "rtt.log"
            connection = mock.Mock()
            connection.connect.side_effect = RuntimeError("offline")
            argv = [
                "rtt_reader.py", "--config", str(config),
                "--output", str(output), "--daemonize",
            ]
            with mock.patch.object(RTT_READER.sys, "argv", argv), \
                    mock.patch.object(
                        RTT_READER, "OpenOCDConnection", return_value=connection
                    ) as connection_class:
                with self.assertRaises(SystemExit):
                    RTT_READER.main()
            connection_class.assert_called_once_with(host="localhost", port=7777)


if __name__ == "__main__":
    unittest.main()
