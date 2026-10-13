from pathlib import Path

import pytest
from astropy.io import fits

from raw2lum.astap_solver import (
    _read_wcs,
    acceptable_databases,
    installed_database_families,
    recommended_database,
)


def test_database_selection_for_common_fields(tmp_path: Path) -> None:
    executable = tmp_path / "astap.exe"
    executable.touch()
    (tmp_path / "d20_0100.290").touch()

    assert recommended_database(17.0) == "G05"
    assert recommended_database(25.0) == "W08"
    assert "D20" in acceptable_databases(17.0)
    assert "D20" in acceptable_databases(5.0)
    assert installed_database_families(executable) == ("D20",)


def test_read_tan_wcs(tmp_path: Path) -> None:
    header = fits.Header()
    header["NAXIS"] = 2
    header["NAXIS1"] = 100
    header["NAXIS2"] = 80
    header["CTYPE1"] = "RA---TAN"
    header["CTYPE2"] = "DEC--TAN"
    header["CRVAL1"] = 120.0
    header["CRVAL2"] = 45.0
    header["CRPIX1"] = 51.0
    header["CRPIX2"] = 41.0
    header["CDELT1"] = -0.01
    header["CDELT2"] = 0.01
    path = tmp_path / "test.wcs"
    header.tofile(path, overwrite=True)

    solution = _read_wcs(path, Path("image.CR2"), 100, 80)

    assert solution.center_ra_deg == pytest.approx(120.0, abs=0.02)
    assert solution.center_dec_deg == pytest.approx(45.0, abs=0.02)
    assert solution.pixel_scale_x_arcsec == pytest.approx(36.0)
    assert solution.pixel_scale_y_arcsec == pytest.approx(36.0)
    assert solution.field_width_deg == pytest.approx(0.99, rel=0.01)
