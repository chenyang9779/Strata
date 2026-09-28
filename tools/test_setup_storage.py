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

    def test_rejects_models_folder_as_data_root_before_any_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            model_file = root / "models" / "IQ2_XS" / "original.gguf"
            model_file.parent.mkdir(parents=True)
            model_file.write_bytes(b"keep me")
            settings_file = base / "config" / "settings.json"
            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=settings_file),
                  patch.object(SETUP, "other_installs", return_value=[])):
                SETUP.save_settings({"data_dir": str(base / "Strata-data")})
                original_settings = settings_file.read_bytes()
                with self.assertRaises(SystemExit):
                    SETUP.data_folder(str(root / "models"))
                self.assertTrue(model_file.is_file())
                self.assertFalse((root / "models" / "models").exists())
                self.assertEqual(settings_file.read_bytes(), original_settings)

    def test_rejects_descendant_of_models_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            root.mkdir()
            settings_file = base / "config" / "settings.json"
            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=settings_file),
                  patch.object(SETUP, "other_installs", return_value=[])):
                with self.assertRaises(SystemExit):
                    SETUP.data_folder(str(root / "models" / "other-folder"))
                self.assertFalse((root / "models").exists())
                self.assertFalse(settings_file.exists())

    def test_rejects_models_folder_in_remembered_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            root.mkdir()
            old = base / "old-data"
            model_file = old / "models" / "IQ2_XS" / "original.gguf"
            model_file.parent.mkdir(parents=True)
            model_file.write_bytes(b"keep me")
            settings_file = base / "config" / "settings.json"
            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=settings_file),
                  patch.object(SETUP, "other_installs", return_value=[])):
                SETUP.save_settings({"data_dir": str(old)})
                with self.assertRaises(SystemExit):
                    SETUP.data_folder(str(old / "models"))
                self.assertTrue(model_file.is_file())
                self.assertFalse((old / "models" / "models").exists())
                self.assertEqual(SETUP.load_settings()["data_dir"], str(old))

    def test_move_into_defensively_rejects_own_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "models"
            original = source / "IQ2_XS" / "original.gguf"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"keep me")
            with self.assertRaises(SystemExit):
                SETUP.move_into(source, source / "models")
            self.assertTrue(original.is_file())
            self.assertFalse((source / "models").exists())

    def test_interrupted_nested_storage_is_not_automatically_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            nested = root / "models" / "models" / "IQ2_XS"
            nested.mkdir(parents=True)
            model_file = nested / "original.gguf"
            model_file.write_bytes(b"keep me")
            new_root = base / "Strata-data"
            settings_file = base / "config" / "settings.json"
            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=settings_file),
                  patch.object(SETUP, "other_installs", return_value=[])):
                with self.assertRaises(SystemExit):
                    SETUP.data_folder(str(new_root))
                self.assertTrue(model_file.is_file())
                self.assertFalse(new_root.exists())
                self.assertFalse(settings_file.exists())

    def test_valid_sibling_folder_can_receive_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Strata"
            original = root / "models" / "IQ2_XS" / "original.gguf"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"keep me")
            new_root = base / "Strata-data"
            settings_file = base / "config" / "settings.json"
            with (patch.object(SETUP, "ROOT", root),
                  patch.object(SETUP, "settings_path", return_value=settings_file),
                  patch.object(SETUP, "other_installs", return_value=[])):
                dest, elsewhere = SETUP.data_folder(str(new_root))
                self.assertEqual(dest, new_root)
                self.assertEqual(elsewhere, [])
                self.assertTrue((new_root / "models" / "IQ2_XS" / "original.gguf").is_file())
                self.assertFalse(original.exists())


if __name__ == "__main__":
    unittest.main()
