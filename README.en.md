# PyRaw2Lum

[Čeština](README.md) | [English](README.en.md)

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
- exact numerical arrays and a detailed JSON report.

Normal processing works offline. A small bright-star catalogue for manual
orientation is bundled with the program. Experimental extinction measurement
requires a one-time Gaia GSPC CSV export.

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
6. Select an output folder and PNG size.
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
2. Select a bright star from the list.
3. Move over it in the main preview. An unfiltered 8× magnifier appears.
4. Click its centre in the magnifier. Fine-tune the point with the arrow keys
   or displayed arrow buttons in 0.5-pixel steps.
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
is up, east right, south down, and west left. The panorama has north at the
centre and runs **S – W – N – E – S** from left to right. Its white line marks
the mathematical horizon; a narrow calibrated strip remains below it so nearby
objects and lights are not cut off.

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

### Preparing a Gaia catalogue

Export a CSV from the Gaia archive with this ADQL query; `V = 8` is sufficient
for initial experiments:

```sql
SELECT g.source_id, g.ra, g.dec,
       p.b_jkc_mag, p.v_jkc_mag,
       p.b_jkc_flag, p.v_jkc_flag
FROM gaiadr3.gaia_source AS g
JOIN gaiadr3.synthetic_photometry_gspc AS p
  ON g.source_id = p.source_id
WHERE p.v_jkc_mag BETWEEN 3.0 AND 8.0
  AND p.v_jkc_flag = 1
  AND p.b_jkc_flag = 1
```

`ra`, `dec`, and `v_jkc_mag` are required. `source_id`, `b_jkc_mag`, and the
quality flags are recommended. Gaia GSPC is incomplete for the brightest stars
below roughly 3 mag.

### Measuring extinction

1. On **Sky brightness**, add the light and matching darks, select the correct
   time zone, and obtain a three-star astrometric solution. One-direction
   orientation is insufficient.
2. On **Extinction – experimental**, select that light and the Gaia CSV.
3. Choose **Tracker** for point-like stars or **Fixed tripod**. Fixed-tripod
   mode computes an individual trail length and direction from declination and
   exposure time for every star.
4. For a first run, keep the 20° minimum altitude, `V = 7.5` limit, and
   2.5-pixel aperture.

The Bouguer plot is shown on the tab immediately when the fit finishes, before
files are saved. Click the preview to inspect it at full size. Outputs are
`*_extinkce.json`, `*_extinkce_hvezdy.csv`, and
`*_extinkce_bouguer.png`.

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
selects a successful profile for subsequent processing.

The calibrator still needs a basic PyRaw2Lum camera/lens profile containing the
crop, centre, and image-circle radius. A future Canon 6D Mark I + 8 mm fisheye
setup therefore first needs this geometry added from a sample RAW.

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
- `--language cs|en` – language of rendered labels and messages.

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
