#!/usr/bin/env python3
"""Installer metadata tests for the OrcaRouter uncensored compatibility family."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("strata_setup", ROOT / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class OrcaSetupTests(unittest.TestCase):
    def test_orca_exposes_only_validated_iq3_xxs(self):
        models = [name for name, meta in setup.MODELS.items()
                  if "orca" in meta.get("families", ("qwen", "swift"))]
        self.assertEqual(models, ["ORCA_IQ3_XXS"])
        meta = setup.MODELS["ORCA_IQ3_XXS"]
        self.assertEqual(meta["label"], "IQ3_XXS")
        self.assertEqual(meta["tag"], "IQ3_XXS")
        self.assertEqual(meta["download_gb"], 85.2)
        self.assertFalse(meta["low_ram"])

    def test_orca_family_uses_compat_pack_and_validated_defaults(self):
        fam = setup.FAMILIES["orca"]
        self.assertEqual(fam["pack_args"], ["--compat-bf16"])
        self.assertEqual(fam["validated_context"], 32768)
        self.assertEqual(fam["prefill"], "512")
        self.assertFalse(fam["vision"])
        self.assertTrue(fam["gated"])
        self.assertEqual(
            fam["file"].format(q="ORCA_IQ3_XXS", i=1),
            "Qwen3.8-Flash-Next-Uncensored-IQ3_XXS-00001-of-00002.gguf",
        )

    def test_hugging_face_token_is_only_added_for_gated_family(self):
        with patch.dict(os.environ, {"HF_TOKEN": "test-token"}, clear=False), \
                patch.object(setup.getpass, "getpass") as hidden_prompt:
            self.assertEqual(
                setup.hf_download_headers(setup.FAMILIES["orca"], prompt=True),
                {"Authorization": "Bearer test-token"},
            )
            hidden_prompt.assert_not_called()
            self.assertIsNone(setup.hf_download_headers(setup.FAMILIES["qwen"], prompt=True))

    def test_hugging_face_token_can_be_entered_at_hidden_prompt(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(setup.sys, "stdin") as stdin, \
                patch.object(setup.getpass, "getpass", return_value="  hf-prompted-token  ") as hidden_prompt:
            stdin.isatty.return_value = True
            self.assertEqual(
                setup.hf_download_headers(setup.FAMILIES["orca"], prompt=True),
                {"Authorization": "Bearer hf-prompted-token"},
            )
            hidden_prompt.assert_called_once()
            self.assertNotIn("HF_TOKEN", os.environ)
            self.assertNotIn("HUGGING_FACE_HUB_TOKEN", os.environ)

    def test_hugging_face_prompt_is_skipped_without_a_terminal(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(setup.sys, "stdin") as stdin, \
                patch.object(setup.getpass, "getpass") as hidden_prompt:
            stdin.isatty.return_value = False
            self.assertIsNone(setup.hf_download_headers(setup.FAMILIES["orca"], prompt=True))
            hidden_prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
