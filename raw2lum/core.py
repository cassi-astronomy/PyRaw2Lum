"""Fotometricke jadro PyRaw2Lum."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Callable
from zoneinfo import ZoneInfo

import exifread
import numpy as np
import rawpy

from .color_analysis import SkyColorSummary, compute_color_indices, summarize_color
from .i18n import get_language, tr
from .palette import colorize
from .photometric_calibration import load_star_calibration
from .profiles import InstrumentProfile, profile_for_camera, rectilinear_profile
from .vignetting import VignettingCalibration, load_vignetting_calibration

ARCSEC_RAD = math.pi / 180.0 / 3600.0
ZERO_MAG_ILLUMINANCE = 2.54e-6
MSA_LUMINANCE_ZERO = ZERO_MAG_ILLUMINANCE / (ARCSEC_RAD**2)


def _vignetting_transmissions(
    profile: InstrumentProfile,
    custom: VignettingCalibration | None,
    shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return exactly one flat-field correction source for each RGB channel."""

    if custom is not None:
        return tuple(custom.transmission(channel, shape) for channel in ("R", "G", "B"))
    built_in = profile.vignetting(shape)
    return built_in, built_in, built_in


def _rectilinear_solid_angle_correction(
    profile: InstrumentProfile, shape: tuple[int, int]
) -> np.ndarray:
    """Normalize the changing sky solid angle of a rectilinear sensor cell.

    A point-source vignetting calibration measures optical throughput, while
    extended-sky radiance also needs the gnomonic pixel solid-angle Jacobian.
    The correction is one on the optical axis and rises towards the corners.
    """

    height, width = shape
    yy, xx = np.indices(shape, dtype=np.float64)
    sensor_height_mm = profile.sensor_width_mm * profile.input_height / profile.input_width
    x_over_f = ((xx + 0.5) / width - 0.5) * profile.sensor_width_mm / profile.focal_length_mm
    y_over_f = ((yy + 0.5) / height - 0.5) * sensor_height_mm / profile.focal_length_mm
    return np.power(1.0 + x_over_f * x_over_f + y_over_f * y_over_f, 1.5)


@dataclass(frozen=True)
class ExifData:
    camera_model: str
    exposure_s: float
    iso: float
    aperture: float
    focal_length_mm: float | None
    captured_at: str | None
    lens_model: str | None


@dataclass
class AnalysisResult:
    source: Path
    darks_used: tuple[Path, ...]
    profile: InstrumentProfile
    exif: ExifData
    luminance_cd_m2: np.ndarray
    msa: np.ndarray
    color_map: np.ndarray
    zenith_cd_m2: float
    zenith_msa: float
    saturated_fraction: float
    relative_red: np.ndarray
    relative_green: np.ndarray
    relative_blue: np.ndarray
    blue_fraction: np.ndarray
    blue_green_ratio: np.ndarray
    red_green_ratio: np.ndarray
    zenith_color: SkyColorSummary
    calibration_divisor_used: float
    language: str = "cs"
    location: str | None = None
    captured_at_utc: str | None = None
    source_timezone: str = "Europe/Prague"
    north_angle_deg: float | None = None
    orientation_matrix: np.ndarray | None = None
    orientation_info: dict[str, object] | None = None
    vignetting_calibration: str | None = None
    photometric_calibration: str | None = None
    show_horizon_circle: bool = True
    show_altitude_circles: bool = False
    projection_mode: str = "fisheye_equisolid"
    wcs_solution: dict[str, object] | None = None
    site_latitude_deg: float | None = None
    site_longitude_deg: float | None = None
    reference_label: str = "Zenit"
    absolute_calibrated: bool = True

    def report(self) -> dict[str, object]:
        valid = np.isfinite(self.luminance_cd_m2) & (self.luminance_cd_m2 > 0)
        valid_cd = self.luminance_cd_m2[valid]
        valid_msa = self.msa[valid]
        return {
            "source": str(self.source),
            "darks_used": [str(path) for path in self.darks_used],
            "profile": self.profile.key,
            "profile_notes": self.profile.notes,
            "language": self.language,
            "location": self.location,
            "source_timezone": self.source_timezone,
            "captured_at_utc": self.captured_at_utc,
            "north_angle_deg": self.north_angle_deg,
            "camera_to_enu": (
                self.orientation_matrix.tolist()
                if self.orientation_matrix is not None
                else None
            ),
            "orientation": self.orientation_info,
            "projection_mode": self.projection_mode,
            "wcs_solution": self.wcs_solution,
            "vignetting_calibration": self.vignetting_calibration,
            "photometric_calibration": self.photometric_calibration,
            "absolute_calibrated": self.absolute_calibrated,
            "map_overlays": {
                "horizon_circle": self.show_horizon_circle,
                "altitude_circles_10_deg": self.show_altitude_circles,
            },
            "calibration_divisor_used": self.calibration_divisor_used,
            "exif": asdict(self.exif),
            "zenith": {
                "mag_per_arcsec2": self.zenith_msa,
                "cd_per_m2": self.zenith_cd_m2,
            },
            "map": {
                "width": int(self.msa.shape[1]),
                "height": int(self.msa.shape[0]),
                "valid_fraction": float(np.mean(valid)),
                "min_mag_per_arcsec2": float(np.min(valid_msa)),
                "max_mag_per_arcsec2": float(np.max(valid_msa)),
                "min_cd_per_m2": float(np.min(valid_cd)),
                "max_cd_per_m2": float(np.max(valid_cd)),
            },
            "quality": {"saturated_fraction": self.saturated_fraction},
            "sky_color_experimental": self.zenith_color.report(),
        }


def _ratio_value(value: object) -> float:
    if hasattr(value, "num") and hasattr(value, "den"):
        return float(value.num) / float(value.den)
    return float(value)


def read_exif(path: str | Path) -> ExifData:
    path = Path(path)
    # exifread 3.x CR3 nerozpozna a vypisuje zavadejici varovani. Pro CR3
    # proto jdeme rovnou pres metadata z LibRaw/rawpy.
    if path.suffix.lower() == ".cr3":
        tags: dict[str, object] = {}
    else:
        with path.open("rb") as handle:
            tags = exifread.process_file(handle, details=False)

    def required(*names: str):
        for name in names:
            tag = tags.get(name)
            if tag is not None:
                return tag
        raise ValueError(f"V souboru {path.name} chybi EXIF polozka {names[0]}.")

    def first_value(tag: object) -> object:
        values = getattr(tag, "values", None)
        if isinstance(values, (list, tuple)) and values:
            return values[0]
        return tag

    try:
        exposure = _ratio_value(first_value(required("EXIF ExposureTime", "Image ExposureTime")))
        aperture = _ratio_value(first_value(required("EXIF FNumber")))
        iso = _ratio_value(first_value(required("EXIF ISOSpeedRatings", "Image ISOSpeedRatings")))
        focal_tag = tags.get("EXIF FocalLength")
        focal = _ratio_value(first_value(focal_tag)) if focal_tag is not None else None
        captured = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        lens = tags.get("EXIF LensModel")
        model = str(required("Image Model")).strip()
        return ExifData(
            camera_model=model,
            exposure_s=exposure,
            iso=iso,
            aperture=aperture,
            focal_length_mm=focal,
            captured_at=str(captured) if captured is not None else None,
            lens_model=str(lens) if lens is not None else None,
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        # exifread zatim nektere kontejnery CR3 neprecte. LibRaw, ktery
        # pouziva rawpy, pritom zakladni expoziční metadata poskytuje.
        with rawpy.imread(str(path)) as raw:
            other = raw.other
            model_tag = tags.get("Image Model")
            model = str(model_tag).strip() if model_tag is not None else ""
            if not model:
                # Model je v CR3 ulozen jako ASCII retezec uz v hlavicce.
                with path.open("rb") as handle:
                    header = handle.read(65536)
                match = re.search(rb"(Canon EOS [ -~]{2,40}?)\x00", header)
                if match:
                    model = match.group(1).decode("ascii", errors="replace").strip()
            if not model:
                raise ValueError(f"V souboru {path.name} chybi model fotoaparatu.")

            exposure = float(other.shutter_speed)
            aperture = float(other.aperture)
            iso = float(other.iso_speed)
            if exposure <= 0 or aperture <= 0 or iso <= 0:
                raise ValueError(f"V souboru {path.name} chybi platne expozicni udaje.")
            timestamp = other.timestamp
            captured = (
                timestamp.strftime("%Y:%m:%d %H:%M:%S")
                if timestamp is not None
                else None
            )
            lens_info = getattr(raw, "lens", None)
            lens_model = getattr(lens_info, "model", None) if lens_info is not None else None
            focal = float(other.focal_length) if other.focal_length else None
            return ExifData(
                camera_model=model,
                exposure_s=exposure,
                iso=iso,
                aperture=aperture,
                focal_length_mm=focal,
                captured_at=captured,
                lens_model=str(lens_model).strip() if lens_model else None,
            )


def profile_for_image(
    path: str | Path,
    projection_mode: str = "auto",
) -> InstrumentProfile:
    """Select the calibrated fisheye profile or construct a full RAW rectangle."""

    source = Path(path)
    exif = read_exif(source)
    mode = projection_mode
    if mode == "auto":
        mode = "rectilinear" if (exif.focal_length_mm or 0.0) > 10.0 else "fisheye"
    if mode == "fisheye":
        return profile_for_camera(exif.camera_model)
    if mode != "rectilinear":
        raise ValueError(f"Neznamy rezim geometrie {projection_mode!r}.")
    with rawpy.imread(str(source)) as raw:
        raw_height, raw_width = raw.raw_image_visible.shape
    if exif.focal_length_mm is None:
        raise ValueError("Obdelnikovy rezim vyzaduje ohniskovou vzdalenost v EXIFu.")
    return rectilinear_profile(
        exif.camera_model,
        exif.lens_model,
        exif.focal_length_mm,
        exif.aperture,
        raw_width,
        raw_height,
    )


def exif_time_to_utc(captured_at: str | None, source_timezone: str) -> str | None:
    """Prevede EXIF cas bez zony na jednoznacny text v UTC."""

    if not captured_at:
        return None
    try:
        local_time = datetime.strptime(captured_at, "%Y:%m:%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"Neznamy format EXIF casu: {captured_at!r}.") from exc

    if source_timezone == "Europe/Prague":
        zone = ZoneInfo("Europe/Prague")
    elif source_timezone == "UTC":
        zone = timezone.utc
    else:
        match = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", source_timezone)
        if not match:
            raise ValueError(f"Neplatne nastaveni casove zony: {source_timezone!r}.")
        sign = 1 if match.group(1) == "+" else -1
        hours, minutes = int(match.group(2)), int(match.group(3))
        zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
    utc_time = local_time.replace(tzinfo=zone).astimezone(timezone.utc)
    return utc_time.strftime("%Y-%m-%d %H:%M:%S UTC")


def luminance_to_msa(luminance: np.ndarray | float) -> np.ndarray:
    values = np.asarray(luminance, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return -2.5 * np.log10(values / MSA_LUMINANCE_ZERO)


def msa_to_luminance(msa: np.ndarray | float) -> np.ndarray:
    return MSA_LUMINANCE_ZERO * np.power(10.0, -0.4 * np.asarray(msa, dtype=np.float64))


def exposure_normalization_factor(
    iso: float,
    exposure_s: float,
    aperture: float,
    calibration_divisor: float,
) -> float:
    """Normalizace zajistujici stejny jas pro ruzne casy a ISO."""

    if iso <= 0 or exposure_s <= 0 or aperture <= 0:
        raise ValueError("ISO, expozicni cas a clona musi byt kladne hodnoty.")
    return iso * exposure_s / (aperture**2) * calibration_divisor


def _load_visible_crop(
    path: Path,
    profile: InstrumentProfile,
) -> tuple[np.ndarray, int, tuple[str, str, str, str]]:
    with rawpy.imread(str(path)) as raw:
        visible = raw.raw_image_visible
        x0, y0 = profile.crop_x, profile.crop_y
        width, height = profile.input_width, profile.input_height
        if y0 + height > visible.shape[0] or x0 + width > visible.shape[1]:
            raise ValueError(f"Kalibracni vyrez se nevejde do RAW obrazu {path.name}.")
        crop = visible[y0 : y0 + height, x0 : x0 + width].astype(np.float32).copy()
        color_desc = raw.color_desc.decode("ascii")
        color_ids = raw.raw_colors_visible[y0 : y0 + 2, x0 : x0 + 2]
        labels = tuple(color_desc[int(value)] for value in color_ids.ravel())
        return crop, int(raw.white_level), labels


def make_orientation_preview(path: str | Path) -> np.ndarray:
    """Vytvori kontrastni 8bitovy nahled ve stejne geometrii jako jasova mapa."""

    path = Path(path)
    exif = read_exif(path)
    profile = profile_for_camera(exif.camera_model)
    raw_crop, _white_level, _labels = _load_visible_crop(path, profile)
    preview = (
        raw_crop[0::2, 0::2]
        + raw_crop[0::2, 1::2]
        + raw_crop[1::2, 0::2]
        + raw_crop[1::2, 1::2]
    ) / 4.0
    low, high = np.percentile(preview, (5.0, 99.95))
    if not high > low:
        raise ValueError(f"Ze souboru {path.name} nelze vytvorit orientacni nahled.")
    normalized = np.clip((preview - low) / (high - low), 0.0, 1.0)
    # Logaritmicke zesvetleni zviditelni hvezdy a pritom zachova horizont.
    normalized = np.log1p(20.0 * normalized) / math.log(21.0)
    return np.rint(normalized * 255.0).astype(np.uint8)


def dark_matches_light(
    light: ExifData,
    dark: ExifData,
    exposure_tolerance_s: float = 1.0,
) -> bool:
    """True pro stejny fotoaparat/ISO a expozici v zadane toleranci."""

    return (
        light.camera_model == dark.camera_model
        and math.isclose(light.iso, dark.iso, rel_tol=0.0, abs_tol=0.5)
        and abs(light.exposure_s - dark.exposure_s) <= exposure_tolerance_s
    )


def _normalize_dark_paths(dark_paths: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(dark_paths, (str, Path)):
        paths = [Path(dark_paths)]
    else:
        paths = list(dict.fromkeys(Path(path) for path in dark_paths))
    if not paths:
        raise ValueError("Nebyl zadan zadny dark RAW.")
    return paths


def analyze_raw(
    light_path: str | Path,
    dark_paths: str | Path | Sequence[str | Path],
    profile: InstrumentProfile | None = None,
    location: str | None = None,
    source_timezone: str = "Europe/Prague",
    north_angle_deg: float | None = None,
    orientation_matrix: np.ndarray | None = None,
    orientation_info: dict[str, object] | None = None,
    vignetting_calibration_path: str | Path | None = None,
    photometric_calibration_path: str | Path | None = None,
    language: str | None = None,
    show_horizon_circle: bool = True,
    show_altitude_circles: bool = False,
    projection_mode: str = "fisheye",
    wcs_solution: dict[str, object] | None = None,
    site_coordinates: tuple[float, float] | None = None,
) -> AnalysisResult:
    """Analyzuje jeden light RAW s automaticky vybranymi odpovidajicimi darky."""

    light_path = Path(light_path)
    light_exif = read_exif(light_path)
    candidate_paths = _normalize_dark_paths(dark_paths)
    matched_paths = [
        path
        for path in candidate_paths
        if dark_matches_light(light_exif, read_exif(path), exposure_tolerance_s=1.0)
    ]
    if not matched_paths:
        raise ValueError(
            f"Pro {light_path.name} nebyl nalezen dark se stejnym fotoaparatem a ISO "
            f"v toleranci expozice ±1,0 s (light {light_exif.exposure_s:g} s)."
        )
    profile = profile or profile_for_image(light_path, projection_mode)

    if light_exif.camera_model != profile.camera_model:
        raise ValueError(
            f"Profil {profile.key} nepatri fotoaparatu {light_exif.camera_model}."
        )
    if not math.isclose(light_exif.aperture, profile.reference_aperture, abs_tol=0.06):
        raise ValueError(
            f"Profil je kalibrovan pro f/{profile.reference_aperture:g}, "
            f"ale snimek ma f/{light_exif.aperture:g}."
        )

    light, white_level, color_labels = _load_visible_crop(light_path, profile)
    dark_sum = np.zeros_like(light, dtype=np.float32)
    usable_darks: list[Path] = []
    for path in matched_paths:
        dark, _, dark_labels = _load_visible_crop(path, profile)
        if dark.shape != light.shape:
            continue
        if dark_labels != color_labels:
            raise ValueError(f"Dark {path.name} ma jinou fazi Bayerovy masky nez light.")
        dark_sum += dark
        usable_darks.append(path)
    if not usable_darks:
        raise ValueError("Nalezene darky nemaji rozmery kompatibilni s light snimkem.")
    dark = dark_sum / float(len(usable_darks))

    # Pozice barev v Bayerove masce se mezi modely lisi. Kanaly proto
    # neurcujeme podle pozice v 2x2 bunce, ale podle metadat RAWu.
    cells = [
        light[0::2, 0::2] - dark[0::2, 0::2],
        light[0::2, 1::2] - dark[0::2, 1::2],
        light[1::2, 0::2] - dark[1::2, 0::2],
        light[1::2, 1::2] - dark[1::2, 1::2],
    ]
    red = [cell for cell, label in zip(cells, color_labels) if label == "R"]
    green = [cell for cell, label in zip(cells, color_labels) if label == "G"]
    blue = [cell for cell, label in zip(cells, color_labels) if label == "B"]
    if len(red) != 1 or len(green) != 2 or len(blue) != 1:
        raise ValueError(f"Nepodporovana Bayerova maska {color_labels!r}.")
    rr, gg, bb = profile.rgb_radiance
    wr, wg, wb = profile.photopic_weights
    custom_vignetting = None
    if vignetting_calibration_path:
        custom_vignetting = load_vignetting_calibration(vignetting_calibration_path)
        custom_vignetting.validate_for(profile, light_exif.aperture)
    transmission_r, transmission_g, transmission_b = _vignetting_transmissions(
        profile, custom_vignetting, red[0].shape
    )
    # A measured flat replaces the built-in Hollan curve. They are deliberately
    # selected above as mutually exclusive alternatives and never multiplied.
    with np.errstate(divide="ignore", invalid="ignore"):
        relative_red = rr * red[0] / transmission_r
        relative_green = gg * (green[0] + green[1]) / 2.0 / transmission_g
        relative_blue = bb * blue[0] / transmission_b
    if profile.projection == "rectilinear":
        solid_angle_correction = _rectilinear_solid_angle_correction(
            profile, relative_green.shape
        )
        relative_red *= solid_angle_correction
        relative_green *= solid_angle_correction
        relative_blue *= solid_angle_correction
    calibration_divisor = profile.calibration_divisor
    if photometric_calibration_path:
        star_calibration = load_star_calibration(photometric_calibration_path)
        star_calibration.validate_for(profile, light_exif)
        calibration_divisor = star_calibration.calibration_divisor
    exposure_factor = exposure_normalization_factor(
        light_exif.iso,
        light_exif.exposure_s,
        light_exif.aperture,
        calibration_divisor,
    )
    relative_red = relative_red.astype(np.float64) / exposure_factor
    relative_green = relative_green.astype(np.float64) / exposure_factor
    relative_blue = relative_blue.astype(np.float64) / exposure_factor
    luminance = wr * relative_red + wg * relative_green + wb * relative_blue
    # Zaporne hodnoty po odectu darku jsou sum kolem nuly, nikoli zaporna
    # fyzikalni luminance. V numerickych vystupech je proto znacime jako NaN.
    luminance[luminance <= 0] = np.nan

    msa = luminance_to_msa(luminance)
    matrix = None
    if orientation_matrix is not None:
        matrix = np.asarray(orientation_matrix, dtype=np.float64)
        if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
            raise ValueError("Astrometricka orientacni matice musi mit rozmer 3×3.")
        if not np.allclose(matrix.T @ matrix, np.eye(3), atol=1e-5) or not math.isclose(
            float(np.linalg.det(matrix)), 1.0, abs_tol=1e-5
        ):
            raise ValueError("Astrometricka orientacni matice neni platna rotace.")
        height, width = luminance.shape
        yy, xx = np.indices(luminance.shape, dtype=np.float64)
        dx, dy = xx - width / 2.0, yy - height / 2.0
        radius = np.hypot(dx, dy)
        radius_scale = profile.crop_size * profile.focal_length_mm / profile.sensor_width_mm
        if orientation_info is not None:
            fitted_scale = orientation_info.get("projection_radius_scale")
            if fitted_scale is not None:
                radius_scale = float(fitted_scale)
                if not math.isfinite(radius_scale) or radius_scale <= 0:
                    raise ValueError("Neplatne projekcni meritko hvezdne orientace.")
        camera_distance = 2.0 * np.arcsin(np.clip(radius / radius_scale, 0.0, 1.0))
        image_angle = np.arctan2(dy, dx)
        camera_x = np.sin(camera_distance) * np.cos(image_angle)
        camera_y = np.sin(camera_distance) * np.sin(image_angle)
        camera_z = np.cos(camera_distance)
        world_up = matrix[2, 0] * camera_x + matrix[2, 1] * camera_y + matrix[2, 2] * camera_z
        angles = np.degrees(np.arccos(np.clip(world_up, -1.0, 1.0)))
    elif profile.projection == "fisheye_equisolid":
        angles = profile.zenith_angle_deg(luminance.shape)
    else:
        angles = np.full(luminance.shape, np.nan, dtype=np.float64)
    if profile.projection == "rectilinear":
        height, width = luminance.shape
        yy, xx = np.indices(luminance.shape)
        center_radius = max(2.0, min(width, height) * 0.05)
        zenith_mask = (
            (np.hypot(xx - width / 2.0, yy - height / 2.0) <= center_radius)
            & np.isfinite(luminance)
            & (luminance > 0)
        )
        reference_label = "Field center"
    else:
        zenith_mask = (angles <= 5.0) & np.isfinite(luminance) & (luminance > 0)
        reference_label = "Zenit"
    zenith_cd = float(np.nanmedian(luminance[zenith_mask]))
    zenith_msa = float(luminance_to_msa(zenith_cd))
    saturated = np.logical_or.reduce(
        [light[0::2, 0::2] >= white_level, light[0::2, 1::2] >= white_level,
         light[1::2, 0::2] >= white_level, light[1::2, 1::2] >= white_level]
    )
    color_saturated = np.logical_or.reduce(
        [light[0::2, 0::2] >= white_level * 0.98,
         light[0::2, 1::2] >= white_level * 0.98,
         light[1::2, 0::2] >= white_level * 0.98,
         light[1::2, 1::2] >= white_level * 0.98]
    )
    # Pixels outside the vignetting-calibrated radius remain useful for visual
    # context (trees, buildings, nearby lights). Keep them instead of applying
    # an artificial circular mask; their absolute photometry is not guaranteed.
    color_valid = ~color_saturated
    blue_fraction, blue_green_ratio, red_green_ratio = compute_color_indices(
        relative_red, relative_green, relative_blue, color_valid
    )
    zenith_color = summarize_color(
        relative_red,
        relative_green,
        relative_blue,
        zenith_mask & color_valid,
    )

    return AnalysisResult(
        source=light_path,
        darks_used=tuple(usable_darks),
        profile=profile,
        exif=light_exif,
        luminance_cd_m2=luminance.astype(np.float32),
        msa=msa.astype(np.float32),
        color_map=colorize(luminance),
        zenith_cd_m2=zenith_cd,
        zenith_msa=zenith_msa,
        saturated_fraction=float(np.mean(saturated)),
        relative_red=relative_red.astype(np.float32),
        relative_green=relative_green.astype(np.float32),
        relative_blue=relative_blue.astype(np.float32),
        blue_fraction=blue_fraction,
        blue_green_ratio=blue_green_ratio,
        red_green_ratio=red_green_ratio,
        zenith_color=zenith_color,
        calibration_divisor_used=calibration_divisor,
        language=language or get_language(),
        location=location.strip() if location and location.strip() else None,
        captured_at_utc=exif_time_to_utc(light_exif.captured_at, source_timezone),
        source_timezone=source_timezone,
        north_angle_deg=north_angle_deg,
        orientation_matrix=matrix,
        orientation_info=orientation_info,
        vignetting_calibration=(
            str(Path(vignetting_calibration_path)) if vignetting_calibration_path else None
        ),
        photometric_calibration=(
            str(Path(photometric_calibration_path))
            if photometric_calibration_path
            else None
        ),
        show_horizon_circle=show_horizon_circle,
        show_altitude_circles=show_altitude_circles,
        projection_mode=profile.projection,
        wcs_solution=wcs_solution,
        site_latitude_deg=site_coordinates[0] if site_coordinates else None,
        site_longitude_deg=site_coordinates[1] if site_coordinates else None,
        reference_label=reference_label,
        absolute_calibrated=(
            profile.projection == "fisheye_equisolid"
            or photometric_calibration_path is not None
        ),
    )


def process_file(
    light_path: str | Path,
    dark_paths: str | Path | Sequence[str | Path],
    output_dir: str | Path,
    display_scale: int = 2,
    progress: Callable[[str], None] | None = None,
    location: str | None = None,
    source_timezone: str = "Europe/Prague",
    north_angle_deg: float | None = None,
    orientation_matrix: np.ndarray | None = None,
    orientation_info: dict[str, object] | None = None,
    vignetting_calibration_path: str | Path | None = None,
    photometric_calibration_path: str | Path | None = None,
    language: str | None = None,
    show_horizon_circle: bool = True,
    show_altitude_circles: bool = False,
    projection_mode: str = "fisheye",
    wcs_solution: dict[str, object] | None = None,
    site_coordinates: tuple[float, float] | None = None,
) -> AnalysisResult:
    """Analyzuje RAW a ulozi PNG, numericka pole a JSON report."""

    from .rendering import (
        render_blue_fraction_map,
        render_luminance_map,
        render_luminance_panorama,
        render_map,
        render_msa_panorama,
    )

    notify = progress or (lambda _message: None)
    light_path = Path(light_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    language = language or get_language()
    notify(tr(f"Analyzuji {light_path.name}", language))
    result = analyze_raw(
        light_path,
        dark_paths,
        location=location,
        source_timezone=source_timezone,
        north_angle_deg=north_angle_deg,
        orientation_matrix=orientation_matrix,
        orientation_info=orientation_info,
        vignetting_calibration_path=vignetting_calibration_path,
        photometric_calibration_path=photometric_calibration_path,
        language=language,
        show_horizon_circle=show_horizon_circle,
        show_altitude_circles=show_altitude_circles,
        projection_mode=projection_mode,
        wcs_solution=wcs_solution,
        site_coordinates=site_coordinates,
    )
    notify(
        tr(
            "Pouzite darky: "
            + ", ".join(f"{path.name}" for path in result.darks_used),
            language,
        )
    )
    if not result.absolute_calibrated:
        notify(tr(
            "VAROVÁNÍ: obdélníková mapa nemá hvězdnou kalibraci této sestavy; "
            "absolutní nulový bod MSA a cd/m² je pouze experimentální.",
            language,
        ))
    stem = light_path.stem

    msa_png_path = output_dir / f"{stem}_jas_oblohy_MSA.png"
    cd_png_path = output_dir / f"{stem}_jas_oblohy_cd_m2.png"
    render_map(result, msa_png_path, display_scale=display_scale)
    notify(tr(f"Ulozeno {msa_png_path.name}", language))
    render_luminance_map(result, cd_png_path, display_scale=display_scale)
    notify(tr(f"Ulozeno {cd_png_path.name}", language))
    color_png_path = output_dir / f"{stem}_barva_oblohy_B_podil.png"
    render_blue_fraction_map(result, color_png_path, display_scale=display_scale)
    notify(tr(f"Ulozeno {color_png_path.name} (experimentalni RGB index)", language))
    if result.projection_mode == "fisheye_equisolid" and (
        result.north_angle_deg is not None or result.orientation_matrix is not None
    ):
        msa_pano_path = output_dir / f"{stem}_panorama_MSA.png"
        cd_pano_path = output_dir / f"{stem}_panorama_cd_m2.png"
        render_msa_panorama(result, msa_pano_path, display_scale=display_scale)
        notify(tr(f"Ulozeno {msa_pano_path.name}", language))
        render_luminance_panorama(result, cd_pano_path, display_scale=display_scale)
        notify(tr(f"Ulozeno {cd_pano_path.name}", language))
    np.savez_compressed(
        output_dir / f"{stem}_numericka_data.npz",
        msa=np.asarray(result.msa, dtype=np.float32),
        cd_m2=np.asarray(result.luminance_cd_m2, dtype=np.float32),
        relative_r=np.asarray(result.relative_red, dtype=np.float32),
        relative_g=np.asarray(result.relative_green, dtype=np.float32),
        relative_b=np.asarray(result.relative_blue, dtype=np.float32),
        blue_fraction=np.asarray(result.blue_fraction, dtype=np.float32),
        blue_green_ratio=np.asarray(result.blue_green_ratio, dtype=np.float32),
        red_green_ratio=np.asarray(result.red_green_ratio, dtype=np.float32),
    )
    with (output_dir / f"{stem}_report.json").open("w", encoding="utf-8") as handle:
        json.dump(result.report(), handle, ensure_ascii=False, indent=2, allow_nan=False)
    notify(tr(f"Hotovo: {light_path.name}", language))
    return result
