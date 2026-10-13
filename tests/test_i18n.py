"""Tests for Czech/English user-facing text."""

from __future__ import annotations

import unittest

from raw2lum.cli import build_parser
from raw2lum.i18n import set_language, tr


class LocalizationTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("cs")

    def test_exact_gui_translation(self) -> None:
        self.assertEqual(tr("Jas oblohy", "en"), "Sky brightness")
        self.assertEqual(
            tr("PyRaw2Lum – měření jasu oblohy", "en"),
            "PyRaw2Lum – sky brightness measurement",
        )

    def test_dynamic_progress_translation(self) -> None:
        self.assertEqual(
            tr("Analyzuji IMG_0001.CR2", "en"),
            "Analysing IMG_0001.CR2",
        )
        self.assertEqual(
            tr("Ulozeno IMG_0001_jas_oblohy_MSA.png", "en"),
            "Saved IMG_0001_jas_oblohy_MSA.png",
        )

    def test_czech_is_unchanged(self) -> None:
        self.assertEqual(tr("Jas oblohy", "cs"), "Jas oblohy")

    def test_cli_accepts_english(self) -> None:
        args = build_parser().parse_args(
            ["light.CR2", "--dark", "dark.CR2", "--language", "en"]
        )
        self.assertEqual(args.language, "en")


if __name__ == "__main__":
    unittest.main()
