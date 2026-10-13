# Bundled catalogue data

`gaia_gspc_v3_7.csv` is a compact all-sky subset of the Gaia DR3 Synthetic
Photometry Catalogue (GSPC), downloaded from the official ESA Gaia Archive.
It contains Johnson–Kron–Cousins B and V synthetic photometry for sources with
`3.1 <= V <= 7.0`, `abs(c_star) < 0.1`, and flux signal-to-noise above 50 in
both bands.

The query used was:

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

Important: these very bright GSPC objects have the JKC validation flags set to
zero and therefore lie outside the fully validated standardisation range. Gaia
still publishes their synthetic magnitudes, but PyRaw2Lum treats calibration
from them as experimental. See the Gaia DR3 GSPC documentation and Gaia
Collaboration et al., A&A 674, A33 (2023).
