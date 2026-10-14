# PyRaw2Lum

**English** | [Česky](README.cs.md)

PyRaw2Lum converts all-sky DSLR RAW images into absolutely calibrated sky
brightness maps in **mag/arcsec² (MSA)** and **cd/m²**. It continues Jan
Hollan's `raw2lum 1.35` project and preserves its calibration, colour scales,
RGB ratios, and vignetting correction.

The name **PyRaw2Lum** distinguishes this Python application from the original
Pascal program. Authorship is described in [AUTHORS.md](AUTHORS.md). The project
uses the **GNU GPL version 2 or later**, like the original program; see
[LICENSE](LICENSE).

Source code and releases are hosted at
[cassi-astronomy/PyRaw2Lum](https://github.com/cassi-astronomy/PyRaw2Lum).

The current profiles support:

- Canon EOS 600D + Sigma 4.5 mm F2.8 EX DC Circular Fisheye at f/3.5
  (the original laboratory calibration),
- Canon EOS R6 Mark II + the same lens at f/3.5 (a relative calibration from
  five paired exposures against the 600D; approximately 1.3% RMS agreement
  and approximately 2.5% maximum deviation).

The R6 has larger pixels, so the same physical lens image circle spans about
2072 pixels instead of 2888 pixels on the 600D. Its profile therefore has its
own centre, crop, and Bayer pattern; images from the two cameras are not
compared pixel by pixel.

PyRaw2Lum rejects an unknown setup or a different aperture. This prevents a
plausible-looking but physically invalid result.

## Features

- batch processing of any number of light RAW files,
- multiple dark RAW files with different exposure times,
- automatic camera, ISO, exposure, aperture, and capture-time reading from
  EXIF,
- automatic dark matching by camera, ISO, and exposure within ±1.0 s,
- master-dark averaging when several matching darks are available,
- normalization of different exposure times and ISO values to one absolute
  brightness scale,
- an optional, separate location name for every light,
- conversion of camera time from CET, CEST, UTC, or another time zone to UTC,
- circular MSA maps using the original 46-colour NPS scale,
- circular cd/m² maps using Hollan's original logarithmic scale,
- an experimental relative blue-channel map and corrected linear R/G/B
  indices for long-term comparisons of sky colour,
- cardinal directions in a separate black border outside the measured image,
- MSA and cd/m² panoramas after orientation has been set,
- north-up circular maps,
- a narrow calibrated strip below the mathematical horizon in panoramas,
- simple orientation using one known cardinal direction,
- full orientation and camera-tilt correction from 2–3 manually selected
  stars,
- experimental atmospheric-extinction measurement by a robust Bouguer fit to
  many catalogue stars, for tracked or fixed-tripod images,
- automatic radial R/G/B vignetting calibration from a series of artificial
  star images, saved as a reusable JSON profile,
- a clean full-screen monitor calibration target,
- persistent management and automatic camera/lens/aperture matching of several
  vignetting profiles,
- experimental absolute stellar calibration from a Bouguer fit,
- automatic WCS solving for 30 mm, 50 mm, and longer lenses through ASTAP,
- exact numerical arrays and a detailed JSON report.

Normal processing works offline. Both the small bright-star catalogue for
manual orientation and a compact all-sky selection of 11,266 Gaia GSPC stars
with `3.1 <= V <= 7.0` are bundled with the program.

## Installation and startup

Python 3.10 or newer is required. Install dependencies with:

```powershell
python -m pip install -r requirements.txt
```

On Windows, double-click `spustit_pyraw2lum.bat`. The old
`spustit_raw2lum.bat` remains as a compatibility shortcut. You can also start
the GUI directly:

```powershell
python -m raw2lum
```

## Language

Use **Jazyk / Language** to switch the whole GUI between Czech and English at
runtime. The choice is saved for the next launch. Titles, cardinal directions,
legend descriptions, messages, and diagnostic plots use the selected language;
scientific units and data filenames remain unchanged.

## Basic workflow

1. Drop one or more files into **Light RAW images**, or use **Add…**.
2. Optionally select a light and assign its individual place name with
   **Location…**.
3. Add all available files to **Dark RAW images**. They may use different
   exposure times.
4. Select the time zone in which the camera clock was set.
5. Optionally set the orientation of each light with **Orientation…**.
6. Select an output folder and PNG size. If desired, enable the mathematical
   horizon and/or 10° altitude circles for the round maps.
7. Press **Start processing**.

Lights and darks can be dragged directly from Windows File Explorer. Paths
containing spaces are supported.

## Lights, darks, and exposure metadata

ISO, exposure time, and aperture do not have to be entered manually. They are
read separately from each RAW. The photometric signal is normalized by:

```text
ISO × exposure time / aperture²
```

Images exposed for, say, 30 s and 300 s therefore produce the same MSA and
cd/m² scale for the same sky brightness, provided that the sensor response is
linear and the image is neither underexposed nor saturated.

For every light, PyRaw2Lum only uses darks with the same camera model, the same
ISO, and an exposure differing by no more than 1.0 s inclusive. If no matching
dark exists, that light is skipped with an explanation and the batch continues.
All matching darks are averaged to reduce random noise.

## Location and time

Every light may have its own optional location name. It appears in the result
title but does not define geographical coordinates.

The **Time stored in EXIF** field supports Europe/Prague with automatic
CET/CEST changes, fixed CET (UTC+1), fixed CEST (UTC+2), UTC, and fixed offsets
from UTC−12 to UTC+14. Result maps and reports always show UTC.

## Map orientation

Orientation is optional and is stored separately for every light. Without it,
both circular maps are generated in the original position, but panoramas are
not created.

### Simple orientation

Click a point in a known direction and select north, east, south, or west. The
point may be Polaris, a compass direction, or a known horizon landmark; its
altitude does not matter. This mode determines cardinal directions but assumes
that the lens pointed exactly at the zenith. It cannot correct camera tilt.

### Astrometric orientation from 2–3 stars

This mode determines cardinal directions and the full camera tilt:

1. Enter the site's latitude and longitude in decimal degrees. North and east
   are positive, south and west negative.
2. Select a bright star from the list. With the list focused, type the first
   letter or several initial letters (`V`, `Ve`, …) to jump directly to Vega;
   repeatedly pressing one letter cycles through stars with that initial.
3. Move over it in the main preview. An unfiltered 8× magnifier appears.
4. Click its centre in the magnifier. Fine-tune the point with the arrow keys
   or displayed arrow buttons in 0.5-pixel steps. `Shift+arrow` uses a
   0.1-pixel step. The crosshair remains fixed while the image moves beneath it.
5. Press **Add clicked star**.
6. Add a second and preferably a third widely separated star.
7. Press **Solve stars and save**.

Two stars are mathematically sufficient; a third is strongly recommended to
reveal a wrong identification or inaccurate click. Polaris is not exactly at
the north celestial pole and can lie roughly 1.2° from the north line depending
on time, so the program deliberately does not force it onto that line.

The solution also derives the actual radial projection scale. That scale is
used consistently for the circular map, zenith, and mathematical horizon. A
pair that is too close, an RMS residual above 0.75°, or an individual residual
above 1° is rejected. RMS below 0.3° is very good; 0.3–0.7° is normally useful;
0.7–0.75° is marginal.

The bundled offline list contains named stars to about magnitude 2.1 from both
hemispheres, based on the
[Bright Star Catalogue V/50](https://cdsarc.cds.unistra.fr/viz-bin/cat/V/50).
For long exposures, mark approximately the centre of a short star trail. Star
positions are calculated for mid-exposure rather than the EXIF start time.

With a star solution, the circular map is resampled to the true zenith: north
is up, east left, south down, and west right, as in an overhead view of the
sky. The panorama uses the natural outward-facing horizon view, has north at
the centre, and runs **S – W – N – E – S** from left to right. Its white line marks
the mathematical horizon; a narrow calibrated strip remains below it so nearby
objects and lights are not cut off.

The circular MSA, luminance, and colour maps follow the same rule. An optional
high-contrast black-and-white line marks true altitude 0°. It is not a mask:
the complete available square RAW crop remains visible, including trees,
buildings, and lights outside the radius covered by the vignetting calibration.
Those outer pixels provide visual context but do not have guaranteed absolute
photometric accuracy. A second optional overlay adds black-edged white circles
at altitudes 10°, 20°, …, 80° and marks the 90° zenith.
Both overlays are calculated only after a full multi-star solution because a
single compass direction cannot determine camera tilt. No artificial circular
image mask is applied. The horizon overlay is enabled by default; the altitude
grid is disabled by default.

## Experimental RAW sky colour

Normal processing also creates `*_barva_oblohy_B_podil.png`, a false-colour
map of the relative blue fraction after dark subtraction, exposure
normalization, profile channel balancing, and vignetting correction:

```text
blue fraction = B / (R + G + B)
```

A fixed 10–50% scale allows different nights to be compared without automatic
recolouring. Display channels are locally smoothed over about 11 × 11 map
pixels to suppress individual stars and noise; the NPZ arrays remain
unsmoothed. The title gives `B/(R+G+B)`, `B/G`, and `R/G` within 5° of the true
zenith. The JSON report contains the same summary, while NPZ stores
`relative_r`, `relative_g`, `relative_b`, `blue_fraction`,
`blue_green_ratio`, and `red_green_ratio`.

These quantities are neither a spectrum nor absolute photopic, scotopic, or
melanopic luminance. They are intended primarily for tracking changes in sky
colour over time. Direct comparison of camera models requires a verified
colour calibration for each model; the R6m2 profile is currently cross-derived
from paired Canon 600D images.

## Experimental atmospheric extinction

The **Extinction – experimental** tab estimates one global extinction
coefficient `k` in mag/airmass from one all-sky image. It measures each suitable
star and robustly fits:

```text
m_inst − V = ZP + k · X + C · (B−V)
```

`X` is air mass, `ZP` the zero point, and `C` an optional colour term. The
colour term is fitted only when enough stars have both B and V values.
Saturated stars, low S/N, catalogue neighbours, duplicate detections, and fit
outliers are rejected automatically.

### Bundled Gaia catalogue

The bundled catalogue contains 11,266 stars to `V = 7`. The default measuring
limit is `V = 6`. An average 50 mm APS-C field (about 25 × 17°) contains roughly
33 such stars by all-sky average. Away from the Milky Way (`|b| ≥ 30°`), the
catalogue averages about 23 stars to `V = 6`, or 78 to `V = 7`, before rejecting
saturation, neighbours, and weak detections.

The catalogue was obtained from the official Gaia archive using:

```sql
SELECT g.source_id, g.ra, g.dec, g.pmra, g.pmdec,
       p.b_jkc_mag, p.v_jkc_mag
FROM gaiadr3.gaia_source AS g
JOIN gaiadr3.synthetic_photometry_gspc AS p USING (source_id)
WHERE p.v_jkc_mag BETWEEN 3.1 AND 7.0
  AND ABS(p.c_star) < 0.1
  AND p.v_jkc_flux / p.v_jkc_flux_error > 50
  AND p.b_jkc_flux / p.b_jkc_flux_error > 50
```

These bright objects have GSPC standardisation validation flag 0. Gaia publishes
their synthetic magnitudes, but they lie outside the fully validated GSPC
range, so the feature remains explicitly experimental. A custom CSV can still
be selected; `ra`, `dec`, and `v_jkc_mag` are required.

### Measuring extinction

1. On **Sky brightness**, add the light and matching darks, select the correct
   time zone, and obtain a three-star astrometric solution. One-direction
   orientation is insufficient.
2. On **Extinction – experimental**, select that light and the Gaia CSV.
3. Choose **Tracker** for point-like stars or **Fixed tripod**. Fixed-tripod
   mode computes an individual trail length and direction from declination and
   exposure time for every star.
4. Leave **Automatic – curve of growth** selected for the first run. Manual
   radius remains available from 1 to 8 map pixels.

Automatic mode measures bright, isolated, unsaturated stars through a series
of radii from 1.5 to 8 pixels. It chooses one common radius where the median
curve of growth contains at least 98.5% of the measured flux and has reached a
stable plateau. The common radius avoids making the aperture itself dependent
on stellar brightness and therefore altitude. If at least five suitable stars
or a stable plateau are unavailable, the automatic run stops instead of
silently returning a questionable result; manual mode can then be used.

The Bouguer plot and aperture contact sheet are shown side by side immediately
when the fit finishes, before files are saved. The contact sheet enlarges
individual stars at the pixel level; yellow outlines show the actual circular
or trail-shaped apertures. It also plots the automatic median curve of growth.
Click the preview to inspect it at full size. Outputs are
`*_extinkce.json`, `*_extinkce_hvezdy.csv`, `*_extinkce_bouguer.png`, and
`*_extinkce_apertury.png`.

This remains a research feature, not a laboratory-validated output. A broad
air-mass range, low fit RMS, and clear apertures free from clouds, the Milky
Way, lights, and strong background gradients improve confidence. Formal slope
uncertainty does not include DSLR spectral response, flat-field, or absolute
calibration systematics.

## Artificial-star vignetting calibration

The **Vignetting calibration** tab measures spatial transmission from a series
of RAW images of the same compact source, for example a small white square on
an otherwise black monitor in a dark room. Keep the square fixed and rotate
the camera about the lens entrance pupil so the source appears across the
image circle.

**Open full screen** displays a single white square or circle of adjustable
size on a clean black field. There is no other text in that window, and any key
closes it, so it can be photographed directly.

- use at least 10, preferably 15–30 RAW images,
- keep camera, lens, aperture, and ISO unchanged,
- include positions near the centre (`r < 0.18`) and edge (`r > 0.72`),
- sample several azimuths at some radii,
- avoid saturation even at the brightest central position,
- repeat the centre position to monitor source stability,
- add matching darks on the **Sky brightness** tab.

The source is found automatically. Its integrated flux is measured separately
in Bayer R, G, and B after local-background subtraction, and saturation is
rejected. Each channel receives a positive radial model:

```text
T(r) = exp(a1·r² + a2·r⁴ + a3·r⁶)
```

Transmission is normalized to `T(0) = 1`. The resulting JSON profile and PNG
control plot show the measured points and R/G/B curves. The GUI automatically
adds a successful profile to its persistent manager. Profiles can be added and
removed on the **Sky brightness** tab, and each light automatically receives a
matching camera, lens, and aperture profile.

The calibrator still needs a basic PyRaw2Lum camera/lens profile containing the
crop, centre, and image-circle radius. A future Canon 6D Mark I + 8 mm fisheye
setup therefore first needs this geometry added from a sample RAW.

## Experimental stellar instrument calibration

**Instrument calibration – stars** derives an absolute conversion coefficient
from the most recent successful extinction measurement. The Bouguer fit
extrapolates stellar brightness above the atmosphere. Its zero point is then
compared with the illuminance of a `V = 0` star and the solid angle of one image
sample. The result is stored separately from vignetting and selected
automatically for the same camera, lens, and aperture.

Use a cloud-free calibration image with many unsaturated stars, weak background
gradients, and a broad air-mass range. This experimental calibration
approximates Johnson V through the camera RGB response; it does not replace a
laboratory measurement of the V(λ) spectral response.

### Automatic ASTAP astrometry for longer lenses

The same tab can run the external [ASTAP](https://www.hnsky.org/astap.htm) for
normal 30 mm, 50 mm, and longer lenses. PyRaw2Lum temporarily develops the RAW
to TIFF, asks ASTAP for a WCS solution, and writes `*_astap_wcs.json` containing
the field centre, dimensions, pixel scale, and complete WCS header. Field
height remains editable; for known Canon 600D, R6m2, and 6D bodies it is
estimated from EXIF focal length and sensor height when the RAW is selected.

ASTAP and a suitable star database must be installed separately. For fields
above 6° and up to 20° high (for example 50 mm + APS-C at about 17°), ASTAP
recommends **G05**; for wider fields it recommends **W08**. Its documentation
also permits the D-series databases from 0.6° upwards, so PyRaw2Lum accepts
them, although G05 is smaller and more efficient for a wide field. PyRaw2Lum
detects the installation and database families but does not download large
databases automatically.

Fisheyes continue to use PyRaw2Lum's manual astrometric solution because their
strong projection is outside a normal WCS/ASTAP solve. The current ASTAP
integration solves and records longer-lens geometry. Full rectangular
brightness and extinction processing through that WCS is the next step; the
current brightness mapper still requires a known instrument geometry profile.

## Output files

Every light creates:

- `*_jas_oblohy_MSA.png` – circular NPS-scale map,
- `*_jas_oblohy_cd_m2.png` – circular Hollan-scale map,
- `*_barva_oblohy_B_podil.png` – experimental relative-blue map,
- `*_numericka_data.npz` – float32 numerical brightness and relative-RGB arrays,
- `*_report.json` – EXIF, profile, darks, zenith value, and diagnostics.

With orientation set, it additionally creates `*_panorama_MSA.png` and
`*_panorama_cd_m2.png`. PNG is intended for viewing and publication. NPZ keeps
the original 1444 × 1444 numerical measurement grid without display
normalization or rotation for further scientific processing.

The MSA image uses the exact original 46-colour scale and contains only
mag/arcsec² values. The cd/m² image uses Hollan's logarithmic scale with five
shades per decade; its upper legend row marks powers of ten and the lower row
the actual colour-decade boundaries. MSA values are not added to that map.

## Command line

Basic batch processing is also available without the GUI:

```powershell
python -m raw2lum.cli image1.CR2 image2.CR2 `
  --dark dark_30s.CR2 dark_180s.CR2 `
  --output output `
  --timezone Europe/Prague `
  --language en
```

Options include:

- `--scale 1|2|3` – presentation PNG size,
- `--location "Jizerka"` – one location for the supplied batch,
- `--timezone Europe/Prague` – time zone used by the EXIF clock,
- `--north-angle` – advanced manual north image angle,
- `--language cs|en` – language of rendered labels and messages,
- `--vignetting-profile profile.json` – explicit CLI vignetting profile,
- `--photometric-profile profile.json` – explicit stellar absolute calibration.
- `--no-horizon-circle` – hide the mathematical horizon in round maps,
- `--altitude-circles` – add 10°–80° altitude circles and the zenith marker.

Interactive astrometric star selection is available in the GUI.

## Accuracy and limitations

- Absolute photometric calibration currently applies only to the documented
  Canon 600D/Sigma 4.5 mm/f/3.5 setup. The R6m2 profile is relative to it.
- Canon 6D or another lens needs separate laboratory or reference calibration
  and its own vignetting correction.
- Saturated, strongly underexposed, or obstructed areas cannot provide reliable
  luminance.
- Astrometric accuracy is limited by clicking, UTC and coordinate accuracy,
  trail length, and the lens geometry model.
- Atmospheric refraction is disabled in the star solution; prefer stars well
  above the horizon.
- The extinction fit does not model spatially varying clouds, aerosol layers,
  or second-order colour extinction and should not be treated as professional
  photometric calibration without inspecting its plot and star table.

## Tests

Run the automated test suite with:

```powershell
python -m unittest discover -s tests -v
```

To compare against the supplied Pascal references, also set
`RAW2LUM_REFERENCE_DIR` to the directory containing the RAW and PPM files.
