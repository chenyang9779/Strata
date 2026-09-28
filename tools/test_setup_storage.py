"""Unit tests for Strata's model-storage selection; no downloads or GPU required."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("strata_setup", ROOT / "setup.py")
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class ModelStorageTests(unittest.TestCase):
    def test_storage_prompt_keeps_default(self):
        default = Path(tempfile.gettempdir()) / "Strata-data"
        with patch("builtins.input", return_value=""):
            self.assertEqual(SETUP.choose_data_dir(default), str(default))

    def test_storage_prompt_requires_absolute_path(self):
        default = Path(tempfile.gettempdir()) / "Strata-data"
        chosen = default.parent / "another-Strata-data"
        with patch("builtins.input", side_effect=["relative-folder", str(chosen)]):
            self.assertEqual(SETUP.choose_data_dir(default), str(chosen))

    def test_storage_prompt_uses_default_on_eof(self):
        default = Path(tempfile.gettempdir()) / "Strata-data"
        with patch("builtins.input", side_effect=EOFError):
            self.assertEqual(SETUP.choose_data_dir(default), str(default))

    def test_changing_storage_retains_old_model_files_and_reuse_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            root.mkdir()
            old = base / "original-model-data"
            model = old / "models" / "IQ2_XS" / "model.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"existing model")
            new = base / "new-model-data"
            cfg = base / "config" / "settings.json"

            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=cfg),
                  patch.object(SETUP, "other_installs", return_value=[])):
                SETUP.save_settings({"data_dir": str(old)})
                selected, elsewhere = SETUP.data_folder(str(new))
                self.assertEqual(selected, new)
                self.assertIn(old, elsewhere)
                self.assertTrue(model.is_file())
                self.assertEqual(SETUP.load_settings()["data_dir"], str(new))
                self.assertIn(str(old), SETUP.load_settings()["previous_data_dirs"])

                # The old folder remains discoverable after the settings file has been updated.
                selected_again, elsewhere_again = SETUP.data_folder(None)
                self.assertEqual(selected_again, new)
                self.assertIn(old, elsewhere_again)


if __name__ == "__main__":
    unittest.main()
