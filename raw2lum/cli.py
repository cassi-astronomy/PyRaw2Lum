"""Prikazova radka pro davkove zpracovani."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import process_file
from .i18n import set_language, tr


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PyRaw2Lum – mereni jasu oblohy z DSLR RAW snimku"
    )
    parser.add_argument("lights", nargs="+", type=Path, help="Jeden nebo vice light RAW souboru")
    parser.add_argument(
        "--dark",
        required=True,
        nargs="+",
        type=Path,
        help="Jeden nebo vice dark RAWu; pro kazdy light se vyberou odpovidajici",
    )
    parser.add_argument("--output", "-o", type=Path, default=Path("vystup"), help="Vystupni slozka")
    parser.add_argument("--scale", type=int, choices=(1, 2, 3), default=2, help="Meritko PNG")
    parser.add_argument("--location", help="Volitelny nazev lokality pro vsechny zadane snimky")
    parser.add_argument(
        "--north-angle",
        type=float,
        help="Volitelny smer severu ve stupnich v obrazovych souradnicich pro panorama",
    )
    parser.add_argument(
        "--timezone",
        default="Europe/Prague",
        help="Zona EXIF casu: Europe/Prague, UTC nebo napr. UTC+01:00",
    )
    parser.add_argument(
        "--vignetting-profile",
        type=Path,
        help="Volitelny JSON profil vinetace z kalibracni karty GUI",
    )
    parser.add_argument(
        "--photometric-profile",
        type=Path,
        help="Volitelny JSON profil hvezdne absolutni fotometricke kalibrace",
    )
    parser.add_argument(
        "--language",
        choices=("cs", "en"),
        default="cs",
        help="Jazyk vystupnich obrazku a hlaseni / output language",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    set_language(args.language)
    failures = 0
    for light in args.lights:
        try:
            process_file(
                light,
                args.dark,
                args.output,
                args.scale,
                progress=print,
                location=args.location,
                source_timezone=args.timezone,
                north_angle_deg=args.north_angle,
                vignetting_calibration_path=args.vignetting_profile,
                photometric_calibration_path=args.photometric_profile,
                language=args.language,
            )
        except Exception as exc:  # CLI musi pokracovat dalsim snimkem
            failures += 1
            print(tr(f"CHYBA {light.name}: {exc}", args.language))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
