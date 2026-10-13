"""Experimentalni mereni atmosfericke extinkce z jednoho all-sky RAWu."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import csv
import json
import math
from pathlib import Path
from typing import Callable

import numpy as np
import rawpy
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
import astropy.units as u
from PIL import Image, ImageDraw

from .i18n import tr

from .core import AnalysisResult, analyze_raw


def bundled_gaia_catalog_path() -> Path:
    """Return the small all-sky Gaia GSPC subset shipped with PyRaw2Lum."""

    return Path(__file__).resolve().parent / "data" / "gaia_gspc_v3_7.csv"


@dataclass(frozen=True)
class CatalogStar:
    source_id: str
    ra_deg: float
    dec_deg: float
    v_mag: float
    b_mag: float | None

    @property
    def b_minus_v(self) -> float | None:
        return None if self.b_mag is None else self.b_mag - self.v_mag


@dataclass(frozen=True)
class StarPhotometry:
    source_id: str
    ra_deg: float
    dec_deg: float
    altitude_deg: float
    azimuth_deg: float
    airmass: float
    v_mag: float
    b_minus_v: float | None
    x: float
    y: float
    trail_length_px: float
    flux: float | None
    snr: float | None
    instrumental_mag: float | None
    used: bool
    reason: str
    residual_mag: float | None = None
    aperture_radius_px: float = 2.5
    trail_angle_deg: float = 0.0


@dataclass(frozen=True)
class ExtinctionResult:
    source: str
    mode: str
    extinction_mag_per_airmass: float
    extinction_std_error: float
    zero_point: float
    color_coefficient: float | None
    fit_rms_mag: float
    used_stars: int
    measured_stars: int
    catalog_candidates: int
    airmass_min: float
    airmass_max: float
    mid_exposure_utc: str
    measurements: tuple[StarPhotometry, ...]
    calibration_divisor_used: float = 1.0
    aperture_mode: str = "manual"
    aperture_radius_px: float = 2.5
    aperture_test_radii_px: tuple[float, ...] = ()
    aperture_growth_curve: tuple[float, ...] = ()
    aperture_calibration_stars: int = 0

    def report(self) -> dict[str, object]:
        result = asdict(self)
        result["measurements"] = [asdict(item) for item in self.measurements]
        return result


def _column(row: dict[str, str], *names: str) -> str | None:
    normalized = {key.lower().strip(): value for key, value in row.items()}
    for name in names:
        value = normalized.get(name.lower())
        if value is not None and value.strip() not in ("", "null", "nan", "--"):
            return value.strip()
    return None


def load_gaia_gspc_csv(path: str | Path, max_v_mag: float = 7.5) -> list[CatalogStar]:
    """Nacte export Gaia GSPC; prijima nazvy sloupcu z Gaia Archive i VizieR."""

    stars: list[CatalogStar] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Katalogovy CSV soubor nema hlavicku.")
        for row in reader:
            ra = _column(row, "ra", "ra_deg", "RA_ICRS")
            dec = _column(row, "dec", "dec_deg", "DE_ICRS")
            vmag = _column(row, "v_jkc_mag", "Vmag", "v_mag")
            if ra is None or dec is None or vmag is None:
                continue
            flag = _column(row, "v_jkc_flag", "Vflag")
            if flag is not None and flag not in ("1", "1.0", "True", "true"):
                continue
            try:
                v_value = float(vmag)
                if not math.isfinite(v_value) or v_value > max_v_mag:
                    continue
                bmag = _column(row, "b_jkc_mag", "Bmag", "b_mag")
                b_flag = _column(row, "b_jkc_flag", "Bflag")
                if b_flag is not None and b_flag not in ("1", "1.0", "True", "true"):
                    bmag = None
                b_value = float(bmag) if bmag is not None else None
                stars.append(
                    CatalogStar(
                        source_id=_column(row, "source_id", "Source") or str(len(stars) + 1),
                        ra_deg=float(ra),
                        dec_deg=float(dec),
                        v_mag=v_value,
                        b_mag=b_value,
                    )
                )
            except ValueError:
                continue
    if not stars:
        raise ValueError(
            "V katalogu nebyly nalezeny sloupce ra, dec a v_jkc_mag/Vmag "
            "s pouzitelnymi hvezdami."
        )
    return stars


def _parse_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)


def mid_exposure_utc(start_utc: str, exposure_s: float) -> str:
    moment = _parse_utc(start_utc) + timedelta(seconds=exposure_s / 2.0)
    return moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"


def _astropy_time(text: str) -> Time:
    clean = text.removesuffix(" UTC")
    return Time(datetime.fromisoformat(clean).replace(tzinfo=timezone.utc))


def _horizontal_vectors(
    stars: list[CatalogStar],
    moment_utc: str,
    latitude_deg: float,
    longitude_deg: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    location = EarthLocation.from_geodetic(lon=longitude_deg * u.deg, lat=latitude_deg * u.deg)
    coordinates = SkyCoord(
        ra=np.asarray([star.ra_deg for star in stars]) * u.deg,
        dec=np.asarray([star.dec_deg for star in stars]) * u.deg,
        frame="icrs",
    )
    horizontal = coordinates.transform_to(
        AltAz(obstime=_astropy_time(moment_utc), location=location, pressure=0 * u.hPa)
    )
    altitude = np.asarray(horizontal.alt.deg, dtype=np.float64)
    azimuth = np.asarray(horizontal.az.deg, dtype=np.float64)
    alt_rad, az_rad = np.radians(altitude), np.radians(azimuth)
    vectors = np.vstack(
        (
            np.cos(alt_rad) * np.sin(az_rad),
            np.cos(alt_rad) * np.cos(az_rad),
            np.sin(alt_rad),
        )
    )
    return vectors, altitude, azimuth


def _airmass(altitude_deg: np.ndarray) -> np.ndarray:
    zenith_deg = 90.0 - altitude_deg
    return 1.0 / (
        np.cos(np.radians(zenith_deg))
        + 0.50572 * np.power(96.07995 - zenith_deg, -1.6364)
    )


def _project_vectors(
    world: np.ndarray,
    rotation: np.ndarray,
    radius_scale: float,
    shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    camera = np.asarray(rotation, dtype=np.float64).T @ world
    distance = np.arccos(np.clip(camera[2], -1.0, 1.0))
    radius = np.sin(distance / 2.0) * radius_scale
    angle = np.arctan2(camera[1], camera[0])
    x = shape[1] / 2.0 + radius * np.cos(angle)
    y = shape[0] / 2.0 + radius * np.sin(angle)
    return x, y, radius


def _track_offsets(x0: float, y0: float, x1: float, y1: float, radius: float) -> np.ndarray:
    length = math.hypot(x1 - x0, y1 - y0)
    count = max(1, int(math.ceil(length * 2.0)))
    line_x = np.linspace(x0, x1, count + 1) - (x0 + x1) / 2.0
    line_y = np.linspace(y0, y1, count + 1) - (y0 + y1) / 2.0
    disk_limit = int(math.ceil(radius))
    disk = np.asarray(
        [
            (dx, dy)
            for dy in range(-disk_limit, disk_limit + 1)
            for dx in range(-disk_limit, disk_limit + 1)
            if dx * dx + dy * dy <= radius * radius
        ],
        dtype=np.float64,
    )
    points = np.vstack(
        [np.column_stack((line_x + dx, line_y + dy)) for dx, dy in disk]
    )
    return np.unique(np.rint(points).astype(np.int32), axis=0)


def _refine_track(
    values: np.ndarray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    aperture_radius: float,
    search_radius: int,
) -> tuple[float, float, float, float]:
    mid_x, mid_y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    offsets = _track_offsets(x0, y0, x1, y1, aperture_radius)
    best_score, best_dx, best_dy = -math.inf, 0, 0
    for dy in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            xx = int(round(mid_x + dx)) + offsets[:, 0]
            yy = int(round(mid_y + dy)) + offsets[:, 1]
            valid = (xx >= 0) & (xx < values.shape[1]) & (yy >= 0) & (yy < values.shape[0])
            sample = values[yy[valid], xx[valid]]
            score = float(np.nansum(sample))
            if score > best_score:
                best_score, best_dx, best_dy = score, dx, dy
    return x0 + best_dx, y0 + best_dy, x1 + best_dx, y1 + best_dy


def _distance_to_segment(xx, yy, x0, y0, x1, y1):
    vx, vy = x1 - x0, y1 - y0
    denominator = vx * vx + vy * vy
    if denominator <= 1e-12:
        return np.hypot(xx - x0, yy - y0)
    position = np.clip(((xx - x0) * vx + (yy - y0) * vy) / denominator, 0.0, 1.0)
    return np.hypot(xx - (x0 + position * vx), yy - (y0 + position * vy))


def _measure_track(
    values: np.ndarray,
    saturated: np.ndarray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    aperture_radius: float,
) -> tuple[float | None, float | None, str]:
    outer = aperture_radius + 5.0
    xmin = max(0, int(math.floor(min(x0, x1) - outer)))
    xmax = min(values.shape[1], int(math.ceil(max(x0, x1) + outer + 1)))
    ymin = max(0, int(math.floor(min(y0, y1) - outer)))
    ymax = min(values.shape[0], int(math.ceil(max(y0, y1) + outer + 1)))
    if xmax <= xmin or ymax <= ymin:
        return None, None, "mimo obraz"
    yy, xx = np.indices((ymax - ymin, xmax - xmin), dtype=np.float64)
    xx += xmin
    yy += ymin
    distance = _distance_to_segment(xx, yy, x0, y0, x1, y1)
    aperture = distance <= aperture_radius
    annulus = (distance >= aperture_radius + 2.0) & (distance <= outer)
    local = values[ymin:ymax, xmin:xmax]
    finite_aperture = aperture & np.isfinite(local)
    finite_annulus = annulus & np.isfinite(local)
    if np.count_nonzero(finite_aperture) < 5 or np.count_nonzero(finite_annulus) < 15:
        return None, None, "nedostatek platnych pixelu"
    if np.any(saturated[ymin:ymax, xmin:xmax][aperture]):
        return None, None, "saturace"
    sky = float(np.nanmedian(local[finite_annulus]))
    flux = float(np.nansum(local[finite_aperture] - sky))
    annulus_values = local[finite_annulus]
    noise = 1.4826 * float(np.nanmedian(np.abs(annulus_values - np.nanmedian(annulus_values))))
    n_ap = np.count_nonzero(finite_aperture)
    n_bg = np.count_nonzero(finite_annulus)
    denominator = max(noise * math.sqrt(n_ap + n_ap * n_ap / n_bg), 1e-20)
    snr = flux / denominator
    if not math.isfinite(flux) or flux <= 0:
        return None, None, "nekladny tok"
    if snr < 8.0:
        return flux, snr, "nizke S/N"
    return flux, snr, ""


def _track_growth_curve(
    values: np.ndarray,
    saturated: np.ndarray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    radii: np.ndarray,
) -> tuple[np.ndarray, float] | None:
    """Return a monotonic curve of growth using one fixed outer sky annulus."""

    maximum = float(np.max(radii))
    outer = maximum + 5.0
    xmin = max(0, int(math.floor(min(x0, x1) - outer)))
    xmax = min(values.shape[1], int(math.ceil(max(x0, x1) + outer + 1)))
    ymin = max(0, int(math.floor(min(y0, y1) - outer)))
    ymax = min(values.shape[0], int(math.ceil(max(y0, y1) + outer + 1)))
    if xmax <= xmin or ymax <= ymin:
        return None
    yy, xx = np.indices((ymax - ymin, xmax - xmin), dtype=np.float64)
    xx += xmin
    yy += ymin
    distance = _distance_to_segment(xx, yy, x0, y0, x1, y1)
    local = values[ymin:ymax, xmin:xmax]
    finite = np.isfinite(local)
    annulus = (distance >= maximum + 2.0) & (distance <= outer) & finite
    if np.count_nonzero(annulus) < 20:
        return None
    if np.any(saturated[ymin:ymax, xmin:xmax][distance <= maximum]):
        return None
    sky_values = local[annulus]
    sky = float(np.nanmedian(sky_values))
    noise = 1.4826 * float(np.nanmedian(np.abs(sky_values - sky)))
    fluxes: list[float] = []
    counts: list[int] = []
    for radius in radii:
        aperture = (distance <= radius) & finite
        counts.append(int(np.count_nonzero(aperture)))
        fluxes.append(float(np.nansum(local[aperture] - sky)))
    growth = np.maximum.accumulate(np.maximum(np.asarray(fluxes), 0.0))
    total = float(growth[-1])
    if not math.isfinite(total) or total <= 0:
        return None
    n_ap = counts[-1]
    n_bg = int(np.count_nonzero(annulus))
    uncertainty = max(noise * math.sqrt(n_ap + n_ap * n_ap / n_bg), 1e-20)
    return growth / total, total / uncertainty


def _automatic_aperture(
    values: np.ndarray,
    saturated: np.ndarray,
    refined: dict[int, tuple[float, float, float, float]],
    candidate_indices: np.ndarray,
    stars: list[CatalogStar],
) -> tuple[float, tuple[float, ...], tuple[float, ...], int]:
    """Choose one unbiased image-wide aperture from bright-star growth curves."""

    radii = np.arange(1.5, 8.01, 0.5, dtype=np.float64)
    curves: list[np.ndarray] = []
    for index in sorted(candidate_indices, key=lambda item: stars[item].v_mag):
        curve = _track_growth_curve(
            values, saturated, *refined[int(index)], radii
        )
        if curve is not None and curve[1] >= 20.0:
            curves.append(curve[0])
        if len(curves) >= 60:
            break
    if len(curves) < 5:
        raise ValueError(
            "Automaticka apertura nema alespon 5 jasnych nesaturovanych hvezd "
            "s S/N >= 20. Pouzijte rucni polomer."
        )
    median = np.median(np.vstack(curves), axis=0)
    # Require 98.5 % of the flux represented by the tested range.  Two final
    # steps must add less than 2.5 %, otherwise the curve has not plateaued.
    if median[-1] - median[-3] > 0.025:
        raise ValueError(
            "Krivka rustu nedosahla do 8 px stabilniho plateau. "
            "Zkontrolujte stopy hvezd nebo pouzijte rucni polomer."
        )
    reached = np.flatnonzero(median >= 0.985)
    selected_index = int(reached[0]) if len(reached) else len(radii) - 1
    selected_index = min(max(selected_index, 2), len(radii) - 1)
    return (
        float(radii[selected_index]),
        tuple(float(value) for value in radii),
        tuple(float(value) for value in median),
        len(curves),
    )


def _saturation_cells(source: Path, result: AnalysisResult) -> np.ndarray:
    profile = result.profile
    with rawpy.imread(str(source)) as raw:
        visible = raw.raw_image_visible
        crop = visible[
            profile.crop_y : profile.crop_y + profile.crop_size,
            profile.crop_x : profile.crop_x + profile.crop_size,
        ]
        threshold = raw.white_level * 0.98
        return np.logical_or.reduce(
            [
                crop[0::2, 0::2] >= threshold,
                crop[0::2, 1::2] >= threshold,
                crop[1::2, 0::2] >= threshold,
                crop[1::2, 1::2] >= threshold,
            ]
        )


def _robust_fit(measurements: list[StarPhotometry]):
    valid = [item for item in measurements if item.instrumental_mag is not None and item.used]
    color_complete = [item for item in valid if item.b_minus_v is not None]
    use_color = len(color_complete) >= max(8, len(valid) // 2)
    if use_color:
        valid = color_complete
    indices = np.arange(len(valid))
    for _ in range(6):
        selected = [valid[index] for index in indices]
        columns = [np.ones(len(selected)), np.asarray([item.airmass for item in selected])]
        if use_color:
            colors = np.asarray([item.b_minus_v for item in selected], dtype=np.float64)
            columns.append(colors)
        design = np.column_stack(columns)
        target = np.asarray([item.instrumental_mag - item.v_mag for item in selected])
        coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
        residual = target - design @ coefficients
        mad = 1.4826 * np.median(np.abs(residual - np.median(residual)))
        if mad <= 1e-9:
            break
        keep_local = np.abs(residual - np.median(residual)) <= max(3.0 * mad, 0.08)
        new_indices = indices[keep_local]
        if len(new_indices) == len(indices):
            break
        indices = new_indices
        if len(indices) < (8 if use_color else 6):
            break
    if len(indices) < (8 if use_color else 6):
        raise ValueError("Po kontrole odlehlych bodu zustalo prilis malo hvezd.")
    selected = [valid[index] for index in indices]
    if np.ptp([item.airmass for item in selected]) < 0.15:
        raise ValueError(
            "Pouzite hvezdy nepokryvaji dostatecny rozsah vzdusne hmoty (minimum je 0,15)."
        )
    columns = [np.ones(len(selected)), np.asarray([item.airmass for item in selected])]
    if use_color:
        columns.append(np.asarray([item.b_minus_v for item in selected]))
    design = np.column_stack(columns)
    target = np.asarray([item.instrumental_mag - item.v_mag for item in selected])
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ coefficients
    dof = len(target) - design.shape[1]
    variance = float(residual @ residual / max(dof, 1))
    covariance = variance * np.linalg.inv(design.T @ design)
    return valid, indices, coefficients, residual, math.sqrt(max(0.0, covariance[1, 1]))


def _isolated_candidates(
    indices: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    stars: list[CatalogStar],
    exclusion_radius: float,
    maximum_count: int = 2000,
    stratify: np.ndarray | None = None,
) -> np.ndarray:
    """Vybere prostorove izolovane hvezdy bez kvadratickeho porovnavani."""

    cell = max(exclusion_radius, 1.0)
    bins: dict[tuple[int, int], list[int]] = {}
    for index in indices:
        key = (int(math.floor(x[index] / cell)), int(math.floor(y[index] / cell)))
        bins.setdefault(key, []).append(int(index))
    isolated: list[int] = []
    for index in indices:
        key_x = int(math.floor(x[index] / cell))
        key_y = int(math.floor(y[index] / cell))
        has_neighbor = False
        for grid_y in range(key_y - 1, key_y + 2):
            for grid_x in range(key_x - 1, key_x + 2):
                for other in bins.get((grid_x, grid_y), ()):
                    if other == index or stars[other].v_mag > stars[index].v_mag + 5.0:
                        continue
                    if math.hypot(x[index] - x[other], y[index] - y[other]) <= exclusion_radius:
                        has_neighbor = True
                        break
                if has_neighbor:
                    break
            if has_neighbor:
                break
        if not has_neighbor:
            isolated.append(int(index))

    if len(isolated) <= maximum_count:
        return np.asarray(isolated, dtype=np.int64)
    if stratify is None:
        ordered = sorted(isolated, key=lambda item: (stars[item].v_mag, item))
        return np.asarray(ordered[:maximum_count], dtype=np.int64)
    # Stejny pocet nejjasnejsich hvezd ze ctyr pasem vysky zachova rozsah X.
    values = np.asarray([stratify[item] for item in isolated], dtype=np.float64)
    edges = np.linspace(float(np.min(values)), float(np.max(values)) + 1e-9, 5)
    selected: list[int] = []
    quota = maximum_count // 4
    for band in range(4):
        members = [
            item
            for item in isolated
            if edges[band] <= stratify[item] < edges[band + 1]
        ]
        selected.extend(sorted(members, key=lambda item: stars[item].v_mag)[:quota])
    if len(selected) < maximum_count:
        remaining = sorted(
            (item for item in isolated if item not in set(selected)),
            key=lambda item: stars[item].v_mag,
        )
        selected.extend(remaining[: maximum_count - len(selected)])
    return np.asarray(selected, dtype=np.int64)


def measure_extinction(
    light_path: str | Path,
    dark_paths,
    catalog_path: str | Path,
    orientation_matrix: np.ndarray,
    orientation_info: dict[str, object],
    latitude_deg: float,
    longitude_deg: float,
    source_timezone: str,
    mode: str = "tracker",
    minimum_altitude_deg: float = 20.0,
    maximum_v_mag: float = 7.5,
    aperture_mode: str = "auto",
    aperture_radius_px: float = 2.5,
    vignetting_calibration_path: str | Path | None = None,
    photometric_calibration_path: str | Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> ExtinctionResult:
    """Zmeri globalni extinkcni koeficient z jednoho orientovaneho snimku."""

    notify = progress or (lambda _message: None)
    if mode not in ("tracker", "fixed"):
        raise ValueError("Rezim musi byt 'tracker' nebo 'fixed'.")
    if aperture_mode not in ("auto", "manual"):
        raise ValueError("Rezim apertury musi byt 'auto' nebo 'manual'.")
    result = analyze_raw(
        light_path,
        dark_paths,
        source_timezone=source_timezone,
        orientation_matrix=orientation_matrix,
        orientation_info=orientation_info,
        vignetting_calibration_path=vignetting_calibration_path,
        photometric_calibration_path=photometric_calibration_path,
    )
    if result.captured_at_utc is None:
        raise ValueError("RAW nema pouzitelny cas expozice.")
    stars = load_gaia_gspc_csv(catalog_path, max_v_mag=maximum_v_mag)
    mid_utc = mid_exposure_utc(result.captured_at_utc, result.exif.exposure_s)
    start_utc = result.captured_at_utc
    end_moment = _parse_utc(start_utc) + timedelta(seconds=result.exif.exposure_s)
    end_utc = end_moment.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"
    notify(f"Katalog: {len(stars)} hvezd do V={maximum_v_mag:g}")

    world_mid, altitude, azimuth = _horizontal_vectors(
        stars, mid_utc, latitude_deg, longitude_deg
    )
    radius_scale = float(
        orientation_info.get(
            "projection_radius_scale",
            result.profile.crop_size * result.profile.focal_length_mm / result.profile.sensor_width_mm,
        )
    )
    x_mid, y_mid, radius = _project_vectors(
        world_mid, orientation_matrix, radius_scale, result.luminance_cd_m2.shape
    )
    if mode == "fixed":
        world_start, _, _ = _horizontal_vectors(stars, start_utc, latitude_deg, longitude_deg)
        world_end, _, _ = _horizontal_vectors(stars, end_utc, latitude_deg, longitude_deg)
        x0, y0, _ = _project_vectors(
            world_start, orientation_matrix, radius_scale, result.luminance_cd_m2.shape
        )
        x1, y1, _ = _project_vectors(
            world_end, orientation_matrix, radius_scale, result.luminance_cd_m2.shape
        )
    else:
        x0, y0, x1, y1 = x_mid.copy(), y_mid.copy(), x_mid.copy(), y_mid.copy()

    air = _airmass(altitude)
    inside = (
        (altitude >= minimum_altitude_deg)
        & (radius <= result.profile.max_calibrated_radius - 8.0)
        & (x_mid >= 8)
        & (x_mid < result.luminance_cd_m2.shape[1] - 8)
        & (y_mid >= 8)
        & (y_mid < result.luminance_cd_m2.shape[0] - 8)
    )
    candidate_indices = np.flatnonzero(inside)
    if len(candidate_indices) < 10:
        raise ValueError("Katalog obsahuje v kalibrovane casti oblohy mene nez 10 hvezd.")

    saturation = _saturation_cells(Path(light_path), result)
    rms_deg = float(orientation_info.get("rms_deg", 1.0))
    search_px = max(3, min(24, int(math.ceil(max(1.2, 1.8 * rms_deg) * radius_scale * math.pi / 360.0))))
    initial_count = len(candidate_indices)
    isolation_aperture = 8.0 if aperture_mode == "auto" else aperture_radius_px
    candidate_indices = _isolated_candidates(
        candidate_indices,
        x_mid,
        y_mid,
        stars,
        exclusion_radius=2.0 * search_px + 2.5 * isolation_aperture,
        stratify=altitude,
    )
    notify(
        f"Izolovane kandidatky: {len(candidate_indices)}/{initial_count} "
        f"(hledaci okoli ±{search_px} px)"
    )
    if len(candidate_indices) < 10:
        raise ValueError("Po vylouceni katalogovych sousedu zustalo mene nez 10 hvezd.")
    refined: dict[int, tuple[float, float, float, float]] = {}
    refinement_radius = min(aperture_radius_px, 2.5) if aperture_mode == "manual" else 2.0
    for number, index in enumerate(candidate_indices, start=1):
        refined[index] = _refine_track(
            result.luminance_cd_m2,
            float(x0[index]),
            float(y0[index]),
            float(x1[index]),
            float(y1[index]),
            refinement_radius,
            search_px,
        )
        if number % 50 == 0:
            notify(f"Nalezeno {number}/{len(candidate_indices)} katalogovych poloh")

    aperture_test_radii: tuple[float, ...] = ()
    aperture_growth_curve: tuple[float, ...] = ()
    aperture_calibration_stars = 0
    if aperture_mode == "auto":
        (
            aperture_radius_px,
            aperture_test_radii,
            aperture_growth_curve,
            aperture_calibration_stars,
        ) = _automatic_aperture(
            result.luminance_cd_m2,
            saturation,
            refined,
            candidate_indices,
            stars,
        )
        notify(
            f"Automaticka apertura: {aperture_radius_px:g} px z "
            f"{aperture_calibration_stars} jasnych hvezd"
        )
    else:
        notify(f"Rucni apertura: {aperture_radius_px:g} px")

    measurements: list[StarPhotometry] = []
    claimed_centers: list[tuple[float, float]] = []
    for index in sorted(candidate_indices, key=lambda item: stars[item].v_mag):
        star = stars[index]
        tx0, ty0, tx1, ty1 = refined[index]
        center_x, center_y = (tx0 + tx1) / 2.0, (ty0 + ty1) / 2.0
        trail_length = math.hypot(tx1 - tx0, ty1 - ty0)
        trail_angle = math.degrees(math.atan2(ty1 - ty0, tx1 - tx0))
        reason = ""
        if any(
            math.hypot(center_x - other_x, center_y - other_y)
            <= max(2.0, aperture_radius_px)
            for other_x, other_y in claimed_centers
        ):
            reason = "duplicitni detekce"
        else:
            claimed_centers.append((center_x, center_y))
        flux = snr = instrumental = None
        if not reason:
            flux, snr, reason = _measure_track(
                result.luminance_cd_m2,
                saturation,
                tx0,
                ty0,
                tx1,
                ty1,
                aperture_radius_px,
            )
            if flux is not None and not reason:
                instrumental = -2.5 * math.log10(flux)
        measurements.append(
            StarPhotometry(
                source_id=star.source_id,
                ra_deg=star.ra_deg,
                dec_deg=star.dec_deg,
                altitude_deg=float(altitude[index]),
                azimuth_deg=float(azimuth[index]),
                airmass=float(air[index]),
                v_mag=star.v_mag,
                b_minus_v=star.b_minus_v,
                x=center_x,
                y=center_y,
                trail_length_px=trail_length,
                flux=flux,
                snr=snr,
                instrumental_mag=instrumental,
                used=instrumental is not None,
                reason=reason,
                aperture_radius_px=aperture_radius_px,
                trail_angle_deg=trail_angle,
            )
        )

    if sum(item.used for item in measurements) < 8:
        reasons: dict[str, int] = {}
        for item in measurements:
            if not item.used:
                reasons[item.reason] = reasons.get(item.reason, 0) + 1
        raise ValueError(
            "Po fotometrickych kontrolach zustalo mene nez 8 hvezd. "
            + ", ".join(f"{key}: {value}" for key, value in sorted(reasons.items()))
        )
    valid, fit_indices, coefficients, residuals, slope_error = _robust_fit(measurements)
    selected_ids = {valid[index].source_id for index in fit_indices}
    residual_by_id = {
        valid[index].source_id: float(residual)
        for index, residual in zip(fit_indices, residuals)
    }
    final_measurements = tuple(
        StarPhotometry(
            **{
                **asdict(item),
                "used": item.source_id in selected_ids,
                "reason": "" if item.source_id in selected_ids else (
                    item.reason or "odlehla hodnota fitu"
                ),
                "residual_mag": residual_by_id.get(item.source_id),
            }
        )
        for item in measurements
    )
    used = [item for item in final_measurements if item.used]
    return ExtinctionResult(
        source=str(light_path),
        mode=mode,
        extinction_mag_per_airmass=float(coefficients[1]),
        extinction_std_error=float(slope_error),
        zero_point=float(coefficients[0]),
        color_coefficient=float(coefficients[2]) if len(coefficients) > 2 else None,
        fit_rms_mag=float(math.sqrt(np.mean(np.square(residuals)))),
        used_stars=len(used),
        measured_stars=sum(item.instrumental_mag is not None for item in final_measurements),
        catalog_candidates=len(candidate_indices),
        airmass_min=min(item.airmass for item in used),
        airmass_max=max(item.airmass for item in used),
        mid_exposure_utc=mid_utc,
        calibration_divisor_used=result.calibration_divisor_used,
        aperture_mode=aperture_mode,
        aperture_radius_px=aperture_radius_px,
        aperture_test_radii_px=aperture_test_radii,
        aperture_growth_curve=aperture_growth_curve,
        aperture_calibration_stars=aperture_calibration_stars,
        measurements=final_measurements,
    )


def make_bouguer_plot(result: ExtinctionResult) -> Image.Image:
    """Vytvori diagnosticky graf pro okamzity nahled i ulozeni do PNG."""

    width, height = 1100, 700
    left, top, right, bottom = 100, 70, 1040, 610
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    measured = [item for item in result.measurements if item.instrumental_mag is not None]
    plot_items = [
        item
        for item in measured
        if result.color_coefficient is None or item.b_minus_v is not None
    ]
    x_values = [item.airmass for item in plot_items]
    y_values = [
        item.instrumental_mag
        - item.v_mag
        - (result.color_coefficient or 0.0) * (item.b_minus_v or 0.0)
        for item in plot_items
    ]
    x_min, x_max = min(x_values), max(x_values)
    x_pad = max(0.05, 0.05 * (x_max - x_min))
    x_min, x_max = x_min - x_pad, x_max + x_pad
    line_ends = [
        result.zero_point + result.extinction_mag_per_airmass * x_min,
        result.zero_point + result.extinction_mag_per_airmass * x_max,
    ]
    y_min, y_max = min(y_values + line_ends), max(y_values + line_ends)
    y_pad = max(0.08, 0.08 * (y_max - y_min))
    y_min, y_max = y_min - y_pad, y_max + y_pad

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * (right - left)

    def py(value: float) -> float:
        return bottom - (value - y_min) / (y_max - y_min) * (bottom - top)

    draw.rectangle((left, top, right, bottom), outline="#333333", width=2)
    for tick in np.linspace(x_min, x_max, 6):
        x = px(float(tick))
        draw.line((x, bottom, x, bottom + 7), fill="#333333", width=1)
        draw.text((x - 20, bottom + 12), f"{tick:.2f}", fill="#222222")
    for tick in np.linspace(y_min, y_max, 6):
        y = py(float(tick))
        draw.line((left - 7, y, left, y), fill="#333333", width=1)
        draw.text((12, y - 7), f"{tick:.2f}", fill="#222222")
    draw.line(
        (px(x_min), py(line_ends[0]), px(x_max), py(line_ends[1])),
        fill="#d02020",
        width=4,
    )
    for item, value in zip(plot_items, y_values):
        x, y = px(item.airmass), py(value)
        color = "#1257b0" if item.used else "#aaaaaa"
        radius = 4 if item.used else 3
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    draw.text(
        (left, 22), tr("Bougueruv diagram atmosfericke extinkce"), fill="#111111"
    )
    draw.text(
        (left + 390, 22),
        f"k = {result.extinction_mag_per_airmass:.4f} +/- "
        f"{result.extinction_std_error:.4f} mag/airmass; RMS = {result.fit_rms_mag:.3f} mag",
        fill="#111111",
    )
    draw.text((left + 390, 650), tr("Vzduchova hmota X"), fill="#111111")
    draw.text(
        (left, 650), tr("modre = pouzite, sede = odmitnute"), fill="#555555"
    )
    draw.text((12, 45), "m_inst - V - C(B-V)", fill="#111111")
    return image


def make_aperture_diagnostic(
    preview: np.ndarray, result: ExtinctionResult
) -> Image.Image:
    """Make a pixel-level contact sheet and curve-of-growth aperture check."""

    width, height = 800, 700
    image = Image.new("RGB", (width, height), "#111111")
    draw = ImageDraw.Draw(image)
    mode = tr("automatická") if result.aperture_mode == "auto" else tr("ruční")
    draw.text(
        (20, 14),
        tr("Kontrola fotometrických apertur")
        + f" – {mode}, r = {result.aperture_radius_px:g} px",
        fill="white",
    )
    source = Image.fromarray(np.asarray(preview, dtype=np.uint8), mode="L")
    used = sorted(
        (item for item in result.measurements if item.used),
        key=lambda item: item.altitude_deg,
    )
    if len(used) > 12:
        indices = np.linspace(0, len(used) - 1, 12).round().astype(int)
        used = [used[int(index)] for index in indices]
    tile_w, tile_h = 195, 145
    image_side = 108
    for number, item in enumerate(used):
        column, row = number % 4, number // 4
        tile_x, tile_y = 10 + column * tile_w, 46 + row * tile_h
        half = max(
            6,
            int(math.ceil(item.aperture_radius_px + item.trail_length_px / 2.0 + 4.0)),
        )
        left = int(round(item.x)) - half
        top = int(round(item.y)) - half
        crop = source.crop((left, top, left + 2 * half + 1, top + 2 * half + 1))
        crop = crop.resize((image_side, image_side), Image.Resampling.NEAREST).convert("RGB")
        image.paste(crop, (tile_x, tile_y))
        scale = image_side / (2 * half + 1)
        cx = tile_x + (item.x - left) * scale
        cy = tile_y + (item.y - top) * scale
        radius = item.aperture_radius_px * scale
        trail = item.trail_length_px * scale
        angle = math.radians(item.trail_angle_deg)
        dx, dy = math.cos(angle) * trail / 2.0, math.sin(angle) * trail / 2.0
        p0, p1 = (cx - dx, cy - dy), (cx + dx, cy + dy)
        if trail < 0.5:
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline="#ffe34d",
                width=2,
            )
        else:
            nx, ny = -math.sin(angle) * radius, math.cos(angle) * radius
            draw.line((p0[0] + nx, p0[1] + ny, p1[0] + nx, p1[1] + ny), fill="#ffe34d", width=2)
            draw.line((p0[0] - nx, p0[1] - ny, p1[0] - nx, p1[1] - ny), fill="#ffe34d", width=2)
            for px, py in (p0, p1):
                draw.ellipse(
                    (px - radius, py - radius, px + radius, py + radius),
                    outline="#ffe34d",
                    width=2,
                )
        draw.line((cx - 4, cy, cx + 4, cy), fill="#00ffff", width=1)
        draw.line((cx, cy - 4, cx, cy + 4), fill="#00ffff", width=1)
        draw.text(
            (tile_x, tile_y + image_side + 4),
            f"V {item.v_mag:.1f}  h {item.altitude_deg:.0f}°  r {item.aperture_radius_px:g}",
            fill="#dddddd",
        )

    curve_top, curve_bottom = 510, 660
    curve_left, curve_right = 65, 770
    if result.aperture_test_radii_px and result.aperture_growth_curve:
        draw.rectangle((curve_left, curve_top, curve_right, curve_bottom), outline="#888888")
        radii = np.asarray(result.aperture_test_radii_px)
        growth = np.asarray(result.aperture_growth_curve)

        def curve_x(value: float) -> float:
            return curve_left + (value - radii[0]) / (radii[-1] - radii[0]) * (curve_right - curve_left)

        # Use a fixed 0.75–1.005 visible range while retaining labels as fractions.
        def visible_y(value: float) -> float:
            return curve_bottom - (np.clip(value, 0.75, 1.005) - 0.75) / 0.255 * (curve_bottom - curve_top)

        points = [(curve_x(float(r)), visible_y(float(g))) for r, g in zip(radii, growth)]
        draw.line(points, fill="#43c6ff", width=3)
        threshold_y = visible_y(0.985)
        draw.line((curve_left, threshold_y, curve_right, threshold_y), fill="#777777", width=1)
        selected_x = curve_x(result.aperture_radius_px)
        draw.line((selected_x, curve_top, selected_x, curve_bottom), fill="#ffe34d", width=2)
        draw.text((curve_left, curve_top - 19), tr("Medián křivky růstu jasných hvězd"), fill="white")
        draw.text((12, threshold_y - 7), "98.5%", fill="#bbbbbb")
        for radius in radii[::2]:
            x = curve_x(float(radius))
            draw.text((x - 8, curve_bottom + 7), f"{radius:g}", fill="#cccccc")
        draw.text((curve_right - 45, curve_bottom + 7), "r [px]", fill="#cccccc")
    else:
        draw.text(
            (curve_left, curve_top + 30),
            tr("Ruční režim – žlutá hranice ukazuje zadanou aperturu."),
            fill="#dddddd",
        )
    return image


def combine_extinction_preview(
    bouguer: Image.Image, apertures: Image.Image
) -> Image.Image:
    combined = Image.new(
        "RGB", (bouguer.width + apertures.width, max(bouguer.height, apertures.height)), "white"
    )
    combined.paste(bouguer, (0, 0))
    combined.paste(apertures, (bouguer.width, 0))
    return combined


def save_extinction_result(
    result: ExtinctionResult,
    output_dir: str | Path,
    aperture_diagnostic: Image.Image | None = None,
) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source).stem
    json_path = output / f"{stem}_extinkce.json"
    csv_path = output / f"{stem}_extinkce_hvezdy.csv"
    plot_path = output / f"{stem}_extinkce_bouguer.png"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(result.report(), handle, ensure_ascii=False, indent=2, allow_nan=False)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(asdict(result.measurements[0]).keys())
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(item) for item in result.measurements)
    make_bouguer_plot(result).save(plot_path)
    paths: tuple[Path, ...] = (json_path, csv_path, plot_path)
    if aperture_diagnostic is not None:
        aperture_path = output / f"{stem}_extinkce_apertury.png"
        aperture_diagnostic.save(aperture_path)
        paths += (aperture_path,)
    return paths
