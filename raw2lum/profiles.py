"""Kalibrovane profily soustav fotoaparat + objektiv."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class InstrumentProfile:
    key: str
    camera_model: str
    lens_name: str
    focal_length_mm: float
    reference_aperture: float
    crop_x: int
    crop_y: int
    crop_size: int
    sensor_width_mm: float
    calibration_divisor: float
    rgb_radiance: tuple[float, float, float]
    photopic_weights: tuple[float, float, float]
    vignetting_coefficients: tuple[float, ...]
    max_calibrated_radius: float
    notes: str = ""

    @property
    def output_size(self) -> int:
        return self.crop_size // 2

    def vignetting(self, shape: tuple[int, int]) -> np.ndarray:
        """Relativni propustnost objektivu podle puvodniho Pascalu."""

        height, width = shape
        yy, xx = np.indices((height, width), dtype=np.float64)
        cx = width / 2.0
        cy = height / 2.0
        radius = np.rint(np.hypot(xx - cx, yy - cy))
        x = radius / self.max_calibrated_radius
        correction = np.ones_like(x)
        inside = x <= 1.0
        correction[inside] = np.polyval(self.vignetting_coefficients, x[inside])
        return correction

    def zenith_angle_deg(self, shape: tuple[int, int]) -> np.ndarray:
        """Uhlova vzdalenost od stredu podle geometrie Sigma 4.5 mm."""

        height, width = shape
        yy, xx = np.indices((height, width), dtype=np.float64)
        radius = np.hypot(xx - width / 2.0, yy - height / 2.0)
        angular_plane = (
            radius * self.sensor_width_mm * 2.0 / (self.crop_size * self.focal_length_mm)
        )
        arg = angular_plane / 2.0
        angle = np.full_like(arg, np.deg2rad(113.4))
        valid = arg < 0.7072
        angle[valid] = 2.0 * np.arcsin(arg[valid])
        return np.rad2deg(angle)


CANON_600D_SIGMA_45 = InstrumentProfile(
    key="canon_600d_sigma_45_f35",
    camera_model="Canon EOS 600D",
    lens_name="Sigma 4.5 mm F2.8 EX DC Circular Fisheye (kalibrace pri f/3.5)",
    focal_length_mm=5.0,  # hodnota ulozena v EXIF dodanych snimku
    reference_aperture=3.5,
    # dcraw crop byl 2888x2888+1168+266. rawpy ma proti puvodnimu
    # dcraw PGM svisly pocatek posunuty o jeden radek.
    crop_x=1168,
    crop_y=265,
    crop_size=2888,
    sensor_width_mm=14.6,
    calibration_divisor=97.0,
    rgb_radiance=(2.44, 1.0, 1.38),
    photopic_weights=(0.30, 0.59, 0.11),
    vignetting_coefficients=(-9.6619, 19.082, -12.07, 1.5323, 0.5931, -0.1051, 1.0),
    max_calibrated_radius=722.0,
    notes="Prevod z raw2lum 1.35; parametry -MR2.44:1:1.38 -T97 -W14.6.",
)

CANON_R6M2_SIGMA_45 = InstrumentProfile(
    key="canon_r6m2_sigma_45_f35",
    camera_model="Canon EOS R6m2",
    lens_name="Sigma 4.5 mm F2.8 EX DC Circular Fisheye (kalibrace při f/3.5)",
    focal_length_mm=5.0,
    reference_aperture=3.5,
    # Stejny objektiv vytvari stejne velky obrazovy kruh v milimetrech.
    # Vetsi pixely R6m2 jej vzorkuji priblizne 2072 pixely misto 2888
    # pixelu 600D. Vyrez je centrovany na opticke ose v dodanych RAW datech.
    crop_x=1975,
    crop_y=976,
    crop_size=2072,
    # Hodnota 14.6 zachovava puvodni uhlovy model objektivu raw2lum;
    # nejde zde o fyzickou sirku full-frame snimace.
    sensor_width_mm=14.6,
    # Relativni kalibrace z peti dvojic stejne osvetlene kopule proti
    # laboratorne kalibrovanemu profilu 600D. RMS shody je priblizne 1.3 %.
    calibration_divisor=95.67,
    rgb_radiance=(2.2257, 1.08798, 1.33874),
    photopic_weights=(0.30, 0.59, 0.11),
    # Jde o stejny fyzicky objektiv pri stejne clone; profil je vyjadren
    # relativnim polomerem, a proto se prepocita na mensi obrazovy kruh R6m2.
    vignetting_coefficients=(-9.6619, 19.082, -12.07, 1.5323, 0.5931, -0.1051, 1.0),
    max_calibrated_radius=518.0,
    notes=(
        "Relativni kalibrace proti laboratornimu profilu Canon 600D z peti "
        "parovych expozic planetarni kopule; RMS shody 1.3 %, maximum 2.5 %. "
        "Vinetace je uhlove prepocitana z totozneho objektivu Sigma 4.5 mm."
    ),
)

PROFILES = {
    CANON_600D_SIGMA_45.key: CANON_600D_SIGMA_45,
    CANON_R6M2_SIGMA_45.key: CANON_R6M2_SIGMA_45,
}


def profile_for_camera(camera_model: str) -> InstrumentProfile:
    candidates = [p for p in PROFILES.values() if p.camera_model == camera_model]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"Pro fotoaparat {camera_model!r} neni k dispozici kalibrovany profil."
        )
    raise ValueError(
        f"Pro fotoaparat {camera_model!r} existuje vice profilu; vyberte objektiv rucne."
    )
