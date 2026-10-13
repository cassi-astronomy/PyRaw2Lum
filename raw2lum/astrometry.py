"""Rucni astrometricka orientace z dvojice nebo vice jasnych hvezd."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import warnings

import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
import astropy.units as u
from astropy.utils import iers
from astropy.utils.exceptions import AstropyWarning

from .profiles import InstrumentProfile

# Pri offline pouziti staci vestavena IERS tabulka. Orientaci mapy nelimituji
# milivterinove korekce rotace Zeme.
iers.conf.auto_download = False
iers.conf.iers_degraded_accuracy = "ignore"
warnings.filterwarnings(
    "ignore",
    message="Tried to get polar motions for times after IERS data is valid.*",
    category=AstropyWarning,
)


@dataclass(frozen=True)
class BrightStar:
    name: str
    constellation: str
    ra: str
    dec: str
    magnitude: float

    @property
    def label(self) -> str:
        return f"{self.name} – {self.constellation} ({self.magnitude:.2f} mag)"


# Offline vyber pojmenovanych hvezd z Bright Star Catalogue V/50, priblizne
# do 2,1 mag. Tesne dvojhvezdy, ktere DSLR nerozlisi, jsou uvedeny jen jednou.
BRIGHT_STARS = (
    BrightStar("Achernar", "Eridanus", "01 37 42.9", "-57 14 12", 0.46),
    BrightStar("Acrux", "Crux", "12 26 35.9", "-63 05 57", 1.33),
    BrightStar("Adhara", "Canis Major", "06 58 37.5", "-28 58 20", 1.50),
    BrightStar("Aldebaran", "Taurus", "04 35 55.2", "+16 30 33", 0.85),
    BrightStar("Alhena", "Gemini", "06 37 42.7", "+16 23 57", 1.93),
    BrightStar("Alioth", "Ursa Major", "12 54 01.7", "+55 57 35", 1.77),
    BrightStar("Alkaid", "Ursa Major", "13 47 32.4", "+49 18 48", 1.86),
    BrightStar("Alnair", "Grus", "22 08 14.0", "-46 57 40", 1.74),
    BrightStar("Alnilam", "Orion", "05 36 12.8", "-01 12 07", 1.70),
    BrightStar("Alnitak", "Orion", "05 40 45.5", "-01 56 34", 2.05),
    BrightStar("Alpha Centauri", "Centaurus", "14 39 35.9", "-60 50 07", -0.01),
    BrightStar("Alphard", "Hydra", "09 27 35.2", "-08 39 31", 1.98),
    BrightStar("Alpheratz", "Andromeda", "00 08 23.3", "+29 05 26", 2.06),
    BrightStar("Altair", "Aquila", "19 50 47.0", "+08 52 06", 0.77),
    BrightStar("Antares", "Scorpius", "16 29 24.4", "-26 25 55", 0.96),
    BrightStar("Arcturus", "Boötes", "14 15 39.7", "+19 10 57", -0.04),
    BrightStar("Atria", "Triangulum Australe", "16 48 39.9", "-69 01 40", 1.92),
    BrightStar("Avior", "Carina", "08 22 30.8", "-59 30 35", 1.86),
    BrightStar("Bellatrix", "Orion", "05 25 07.9", "+06 20 59", 1.64),
    BrightStar("Betelgeuse", "Orion", "05 55 10.3", "+07 24 25", 0.50),
    BrightStar("Canopus", "Carina", "06 23 57.1", "-52 41 45", -0.72),
    BrightStar("Capella", "Auriga", "05 16 41.4", "+45 59 53", 0.08),
    BrightStar("Castor", "Gemini", "07 34 36.0", "+31 53 18", 1.98),
    BrightStar("Deneb", "Cygnus", "20 41 25.9", "+45 16 49", 1.25),
    BrightStar("Diphda", "Cetus", "00 43 35.4", "-17 59 12", 2.04),
    BrightStar("Dubhe", "Ursa Major", "11 03 43.7", "+61 45 03", 1.79),
    BrightStar("Elnath", "Taurus", "05 26 17.5", "+28 36 27", 1.65),
    BrightStar("Fomalhaut", "Piscis Austrinus", "22 57 39.1", "-29 37 20", 1.16),
    BrightStar("Gacrux", "Crux", "12 31 09.9", "-57 06 48", 1.63),
    BrightStar("Hadar", "Centaurus", "14 03 49.4", "-60 22 23", 0.61),
    BrightStar("Hamal", "Aries", "02 07 10.4", "+23 27 45", 2.00),
    BrightStar("Kaus Australis", "Sagittarius", "18 24 10.3", "-34 23 05", 1.85),
    BrightStar("Kochab", "Ursa Minor", "14 50 42.3", "+74 09 20", 2.08),
    BrightStar("Menkalinan", "Auriga", "05 59 31.7", "+44 56 51", 1.90),
    BrightStar("Menkent", "Centaurus", "14 06 41.0", "-36 22 12", 2.06),
    BrightStar("Miaplacidus", "Carina", "09 13 12.0", "-69 43 02", 1.68),
    BrightStar("Mimosa", "Crux", "12 47 43.2", "-59 41 19", 1.25),
    BrightStar("Mirach", "Andromeda", "01 09 43.9", "+35 37 14", 2.06),
    BrightStar("Mirfak", "Perseus", "03 24 19.4", "+49 51 40", 1.79),
    BrightStar("Mirzam", "Canis Major", "06 22 42.0", "-17 57 21", 1.98),
    BrightStar("Nunki", "Sagittarius", "18 55 15.9", "-26 17 48", 2.02),
    BrightStar("Peacock", "Pavo", "20 25 38.9", "-56 44 06", 1.94),
    BrightStar("Polaris", "Ursa Minor", "02 31 48.7", "+89 15 51", 2.02),
    BrightStar("Pollux", "Gemini", "07 45 18.9", "+28 01 34", 1.14),
    BrightStar("Procyon", "Canis Minor", "07 39 18.1", "+05 13 30", 0.38),
    BrightStar("Rasalhague", "Ophiuchus", "17 34 56.1", "+12 33 36", 2.08),
    BrightStar("Regulus", "Leo", "10 08 22.3", "+11 58 02", 1.35),
    BrightStar("Rigel", "Orion", "05 14 32.3", "-08 12 06", 0.12),
    BrightStar("Saiph", "Orion", "05 47 45.4", "-09 40 11", 2.06),
    BrightStar("Sargas", "Scorpius", "17 37 19.2", "-42 59 52", 1.87),
    BrightStar("Shaula", "Scorpius", "17 33 36.5", "-37 06 14", 1.63),
    BrightStar("Sirius", "Canis Major", "06 45 08.9", "-16 42 58", -1.46),
    BrightStar("Spica", "Virgo", "13 25 11.6", "-11 09 41", 0.98),
    BrightStar("Vega", "Lyra", "18 36 56.3", "+38 47 01", 0.03),
    BrightStar("Wezen", "Canis Major", "07 08 23.5", "-26 23 36", 1.84),
)

STAR_BY_LABEL = {star.label: star for star in BRIGHT_STARS}


@dataclass(frozen=True)
class StarMatch:
    star: BrightStar
    x: float
    y: float


@dataclass(frozen=True)
class OrientationSolution:
    camera_to_enu: np.ndarray
    residual_deg: tuple[float, ...]
    radius_scale: float

    @property
    def rms_deg(self) -> float:
        return math.sqrt(float(np.mean(np.square(self.residual_deg))))


def image_point_to_camera_vector(
    x: float,
    y: float,
    profile: InstrumentProfile,
    radius_scale: float | None = None,
) -> np.ndarray:
    center = profile.output_size / 2.0
    dx, dy = x - center, y - center
    radius = math.hypot(dx, dy)
    radius_scale = radius_scale or (
        profile.crop_size * profile.focal_length_mm / profile.sensor_width_mm
    )
    if radius > profile.max_calibrated_radius or radius >= radius_scale:
        raise ValueError("Oznaceny bod lezi mimo kalibrovanou oblast objektivu.")
    zenith_distance = 2.0 * math.asin(radius / radius_scale)
    angle = math.atan2(dy, dx)
    return np.asarray(
        [
            math.sin(zenith_distance) * math.cos(angle),
            math.sin(zenith_distance) * math.sin(angle),
            math.cos(zenith_distance),
        ],
        dtype=np.float64,
    )


def star_enu_vector(
    star: BrightStar,
    captured_at_utc: str,
    latitude_deg: float,
    longitude_deg: float,
) -> np.ndarray:
    moment = datetime.fromisoformat(captured_at_utc.removesuffix(" UTC")).replace(
        tzinfo=timezone.utc
    )
    location = EarthLocation.from_geodetic(
        lon=longitude_deg * u.deg,
        lat=latitude_deg * u.deg,
    )
    coordinate = SkyCoord(star.ra, star.dec, unit=(u.hourangle, u.deg), frame="icrs")
    with warnings.catch_warnings():
        # Vestavena IERS tabulka je pro mapovou orientaci o nekolik radu
        # presnejsi, nez rucni kliknuti; varovani o obloukovych vterinach
        # proto v offline aplikaci nema uzivatelskou hodnotu.
        warnings.simplefilter("ignore", AstropyWarning)
        horizontal = coordinate.transform_to(
            AltAz(obstime=Time(moment), location=location, pressure=0 * u.hPa)
        )
    altitude = horizontal.alt.radian
    azimuth = horizontal.az.radian
    return np.asarray(
        [
            math.cos(altitude) * math.sin(azimuth),
            math.cos(altitude) * math.cos(azimuth),
            math.sin(altitude),
        ],
        dtype=np.float64,
    )


def solve_orientation(
    matches: list[StarMatch],
    profile: InstrumentProfile,
    captured_at_utc: str,
    latitude_deg: float,
    longitude_deg: float,
) -> OrientationSolution:
    if len(matches) < 2:
        raise ValueError("Pro astrometrickou orientaci oznacte alespon dve hvezdy.")
    if not -90.0 <= latitude_deg <= 90.0:
        raise ValueError("Zemepisna sirka musi byt v rozsahu -90 az +90 stupnu.")
    if not -180.0 <= longitude_deg <= 180.0:
        raise ValueError("Zemepisna delka musi byt v rozsahu -180 az +180 stupnu.")
    if len({match.star.name for match in matches}) != len(matches):
        raise ValueError("Kazdou hvezdu lze pro reseni pouzit jen jednou.")

    world = np.stack(
        [
            star_enu_vector(
                match.star,
                captured_at_utc,
                latitude_deg,
                longitude_deg,
            )
            for match in matches
        ]
    )
    nominal_scale = profile.crop_size * profile.focal_length_mm / profile.sensor_width_mm

    def solve_at_scale(radius_scale: float) -> tuple[float, np.ndarray, np.ndarray]:
        camera = np.stack(
            [
                image_point_to_camera_vector(
                    match.x,
                    match.y,
                    profile,
                    radius_scale=radius_scale,
                )
                for match in matches
            ]
        )
        covariance = camera.T @ world
        left, _singular, right_t = np.linalg.svd(covariance)
        rotation = right_t.T @ left.T
        if np.linalg.det(rotation) < 0:
            right_t[-1, :] *= -1
            rotation = right_t.T @ left.T
        predicted = (rotation @ camera.T).T
        dot = np.clip(np.sum(predicted * world, axis=1), -1.0, 1.0)
        residuals = np.degrees(np.arccos(dot))
        return float(np.mean(np.square(residuals))), rotation, residuals

    nominal_camera = np.stack(
        [
            image_point_to_camera_vector(
                match.x,
                match.y,
                profile,
                radius_scale=nominal_scale,
            )
            for match in matches
        ]
    )
    # Dve temer shodne hvezdne polohy neurcuji stabilne rotaci kolem jejich osy.
    if np.linalg.norm(np.cross(nominal_camera[0], nominal_camera[1])) < 0.08:
        raise ValueError("Vybrane hvezdy jsou prilis blizko u sebe; zvolte vzdalenejsi dvojici.")

    # Stary program mel projekcni meritko pevne dane EXIF ohniskem a rozmery
    # senzoru. Skutecne rybi oko se od idealniho modelu o nekolik procent lisi;
    # tato chyba se u obzoru zesiluje. Hvezdy proto kalibruji i radius_scale.
    lower, upper = nominal_scale * 0.80, nominal_scale * 1.20
    sample_scales = np.linspace(lower, upper, 161)
    sample_errors = np.asarray([solve_at_scale(value)[0] for value in sample_scales])
    best_index = int(np.argmin(sample_errors))
    if best_index in (0, len(sample_scales) - 1):
        raise ValueError(
            "Hvezdne reseni vyzaduje nerealne projekcni meritko. "
            "Zkontrolujte identifikaci hvezd, cas a souradnice."
        )

    # Zjemneni minima zlateho rezu mezi sousednimi body hrubeho hledani.
    a = float(sample_scales[best_index - 1])
    b = float(sample_scales[best_index + 1])
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    c, d = b - golden * (b - a), a + golden * (b - a)
    fc, fd = solve_at_scale(c)[0], solve_at_scale(d)[0]
    for _ in range(45):
        if fc <= fd:
            b, d, fd = d, c, fc
            c = b - golden * (b - a)
            fc = solve_at_scale(c)[0]
        else:
            a, c, fc = c, d, fd
            d = a + golden * (b - a)
            fd = solve_at_scale(d)[0]
    radius_scale = (a + b) / 2.0
    _error, rotation, residual_array = solve_at_scale(radius_scale)
    residuals = tuple(float(value) for value in residual_array)
    return OrientationSolution(rotation, residuals, radius_scale)
