"""Desktop control validation tests (no CUDA, Tk window, downloads or network)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strata_desktop_core as core


class DesktopCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "Strata"
        self.root.mkdir()
        self.settings_dir = self.base / "AppData" / "Strata"
        self.user_dir_patch = patch.object(core, "user_dir", return_value=self.settings_dir)
        self.user_dir_patch.start()
        self.addCleanup(self.user_dir_patch.stop)

    def config(self):
        path = self.root / "strata-iq2_xs.json"
        cfg = {"exe": str(self.root / "engine" / "strata.exe"),
               "args": ["--pack", "existing_pack", "--expert-cache", "auto",
                        "--prefill", "auto", "--max-context", "32768"],
               "cwd": str(self.root), "model_name": "qwen3.8-flash-next-iq2_xs",
               "port": 8080, "vision": {"exe": "vision.exe", "mmproj": "vision.gguf"}}
        core.atomic_json(path, cfg)
        return path

    def runtime(self, **changes):
        result = dict(host="127.0.0.1", port="8080", api_key="", gpu="Auto",
                      cpu_workers="0", vision_threads="0", expert_cache="auto",
                      prefill="auto", fit_max_tokens=False)
        result.update(changes)
        return result

    def test_reject_repo_models_folder_before_touching_files(self):
        original = self.root / "models" / "IQ2_XS" / "original.gguf"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"original")
        for invalid in (original.parent.parent, original.parent, self.root / "packs",
                        self.root / "mtp" / "subdir"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                core.validate_data_root(self.root, invalid)
        self.assertEqual(original.read_bytes(), b"original")
        self.assertFalse((self.root / "models" / "models").exists())

    def test_reject_remembered_models_directory_and_interrupted_nested_move(self):
        previous = self.base / "previous"
        core.atomic_json(self.settings_dir / "settings.json", {"data_dir": str(previous)})
        old = previous / "models" / "IQ2_XS" / "original.gguf"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        with self.assertRaises(ValueError):
            core.validate_data_root(self.root, previous / "models")
        nested = self.root / "models" / "models" / "IQ2_XS"
        nested.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Nested directory"):
            core.validate_data_root(self.root, self.base / "safe-data")
        self.assertTrue(old.is_file())

    def test_valid_sibling_data_root(self):
        requested = self.base / "Strata-data"
        self.assertEqual(core.validate_data_root(self.root, requested), requested.resolve())

    def test_lan_requires_api_key(self):
        with self.assertRaisesRegex(ValueError, "API key"):
            core.validate_runtime("0.0.0.0", "8080", "", "Auto", "0", "0", "auto", "auto")
        self.assertEqual(core.validate_runtime(
            "0.0.0.0", "9000", "private-key", "1", "6", "4", "4096", "2048"), (9000, 6, 4, 1))

    def test_zero_expert_cache_is_rejected_with_default_speculative_engine(self):
        with self.assertRaisesRegex(ValueError, "positive slot count"):
            core.validate_runtime("127.0.0.1", "8080", "", "Auto", "0", "0", "0", "auto")

    def test_invalid_settings_do_not_change_model_json(self):
        path = self.config()
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            core.apply_runtime(path, **self.runtime(host="0.0.0.0"))
        with self.assertRaises(ValueError):
            core.apply_runtime(path, **self.runtime(port="99999"))
        self.assertEqual(path.read_bytes(), original)

    def test_apply_runtime_updates_only_known_fields_and_preserves_others(self):
        path = self.config()
        result = core.apply_runtime(path, **self.runtime(
            host="0.0.0.0", api_key="private-key", port="9080", gpu="1",
            cpu_workers="6", vision_threads="4", expert_cache="4096",
            prefill="2048", fit_max_tokens=True))
        self.assertEqual(result["args"][:2], ["--pack", "existing_pack"])
        self.assertEqual(core.flag_value(result["args"], "--pool-workers", ""), "6")
        self.assertEqual(core.flag_value(result["args"], "--expert-cache", ""), "4096")
        self.assertEqual(core.flag_value(result["args"], "--prefill", ""), "2048")
        self.assertEqual(result["gpu"], 1)
        self.assertEqual(result["vision"]["threads"], 4)
        self.assertTrue(result["fit_max_tokens"])
        self.assertEqual(result["api_key"], "private-key")
        self.assertEqual(result["port"], 9080)
        self.assertEqual(core.read_json(path), result)
        reset = core.apply_runtime(path, **self.runtime())
        self.assertNotIn("--pool-workers", reset["args"])
        self.assertNotIn("gpu", reset)
        self.assertNotIn("threads", reset["vision"])
        self.assertEqual(reset["args"].count("--expert-cache"), 1)
        self.assertEqual(reset["args"].count("--prefill"), 1)

    def test_setup_command_uses_data_root_without_shell_and_existing_gguf(self):
        gguf = self.base / "GGUF"
        gguf.mkdir()
        cmd = core.setup_command(Path("python.exe"), self.root, family="coder", model="IQ1_M",
                                 context=65536, kv="int8", vision="gpu", projection="off",
                                 data_dir=self.base / "Strata-data", gpu="0", gguf_dir=str(gguf))
        self.assertIn("--no-start", cmd)
        self.assertEqual(cmd[cmd.index("--family") + 1], "coder")
        self.assertEqual(Path(cmd[cmd.index("--data-dir") + 1]).resolve(), (self.base / "Strata-data").resolve())
        self.assertEqual(Path(cmd[cmd.index("--gguf-dir") + 1]).resolve(), gguf.resolve())
        with self.assertRaises(ValueError):
            core.setup_command(Path("python.exe"), self.root, family="swift", model="IQ3_S",
                               context=32768, kv="int8", vision="none", projection="off",
                               data_dir=self.base / "Strata-data", gpu="Auto", gguf_dir="")

    def test_server_command_keeps_secret_out_of_process_arguments(self):
        path = self.config()
        cfg = core.apply_runtime(path, **self.runtime(host="0.0.0.0", api_key="secret-example"))
        cmd = core.server_command(Path("python.exe"), self.root, path, cfg)
        self.assertNotIn("secret-example", cmd)
        self.assertNotIn("--api-key", cmd)
        self.assertEqual(cmd[cmd.index("--port") + 1], "8080")

    def test_invalid_mcp_file_is_rejected_before_server_start(self):
        path = self.config()
        bad = self.base / "mcp.json"
        bad.write_text('{"tools":{}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mcpServers"):
            core.server_command(Path("python.exe"), self.root, path, core.read_json(path), str(bad))
        bad.write_text('{"mcpServers":{}}', encoding="utf-8")
        self.assertIn("--mcp-config",
                      core.server_command(Path("python.exe"), self.root, path, core.read_json(path), str(bad)))

    def test_installed_configs_ignore_shared_settings(self):
        path = self.config()
        (self.root / "strata-iq2_xs.shared-settings.json").write_text(
            '{"reasoning_effort":"high"}', encoding="utf-8")
        self.assertEqual([p for p, _ in core.installed_models(self.root)], [path])


if __name__ == "__main__":
    unittest.main()
