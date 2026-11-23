# Tools

These scripts fitted and checked versions 1.x of the profile; `adoucir_look.py --self-test` also checks the current release.

The scripts that fitted and checked HNCS. They are written in Python 3 with comments and reports in French (the reports are what the README tables come from). You do **not** need any of this to use the profile: it is for reproducing or improving it, for example for another lens, another body or another Phocus version.

## What you need

- Python 3 with `numpy`, `scipy`, `Pillow`, `rawpy`, `opencv-python` and `colour-science` (`colour`) for some scripts.
- `exiftool` on the PATH (reads the 3FR tags and checks the written `.dcp`).
- To redo the measurements on your own files (not needed to rerun the fit on `data/`): the 3FR and the same photo exported by Phocus (16-bit TIFF, default HNCS settings, SDR; for a 3FR flagged HDR, switch HDR off in the Phocus sidecar first).
- For the real Camera Raw renders (`valider_acr.py`, `acr_v2.py`): macOS with Photoshop, driven by script. The Photoshop application path is written in `valider_acr.py` for the version I used (2027); change it for yours. Lightroom itself is never launched.
- The `Adobe Standard` profile of the camera, which Lightroom installs (`/Library/Application Support/Adobe/CameraRaw/CameraProfiles/Adobe Standard/Hasselblad 100-22-Coated6 Adobe Standard.dcp`).
- Optional: [dcamprof](https://github.com/Entropy512/dcamprof) 1.0.6, only for `via_dcamprof.py` and one cross-check of `chaine_adobe.py`.

## Where files go

The fitting data are in [`../data/`](../data/README.md): `samples-pass1.npz` and `samples-pass2.npz`, which the scripts read from there. With them, `ajuster.py`, `ajuster_v2.py` and `passe2.py` run from this repository without any raw photo. Outputs are written next to `tools/`, in `measurements/` (reports and figures) and `profiles/` (profiles); these folders are created on the first real run.

Only the scripts that read raw photos (`echantillons.py`, `echantillons_passe2.py` to rebuild the data, `valider_acr.py` and `acr_v2.py` for Camera Raw renders) need a work folder set by `HNCS_WORKDIR` (default `./workdir`): `phocus-entree/` (3FR), `phocus-sortie/` (Phocus TIFF, named `B_<last 4 digits>.tif`), then `phocus-entree-2/` and `phocus-sortie-2/` for the second batch. Other variables: `HNCS_JPEG_DIR` (in-camera JPEGs, first batch only), `HNCS_DCAMPROF` (path to the dcamprof binary). The file naming follows my Hasselblad numbering (`B0000583`).

## What runs from this repository alone

Needs only Python and `data/` (plus `exiftool` for the `.dcp` checks):

```
python3 tools/ajuster.py --sans-planche   # first fit and its report (about 2 minutes); writes measurements/ and profiles/
python3 tools/passe2.py donnees           # the 170 images of both batches, by lens, ISO and light
python3 tools/ajuster.py --self-test
python3 tools/ajuster_v2.py --self-test
python3 tools/passe2.py --self-test   # after ajuster.py (it compares with the v1 profile that ajuster.py writes)
python3 tools/dcp_ecrire.py --self-test
python3 tools/chaine_adobe.py --self-test   # needs Adobe's profile for check (d), skipped without it or without dcamprof
python3 tools/echantillons.py --self-test
python3 tools/echantillons_passe2.py --self-test
python3 tools/acr_v2.py --self-test
python3 tools/via_dcamprof.py --self-test   # reports "ignored" without dcamprof
python3 tools/adoucir_look.py --self-test   # banding check of release/HNCS-Hasselblad-X2D-II.dcp
```

`ajuster.py` and `passe2.py` also read Adobe's `Adobe Standard` profile of the camera (installed by Lightroom, see above). `valider_acr.py --self-test` needs Photoshop, your 3FR and the installed profiles, so it cannot run without them. The v1 profile that `passe2.py` compares with is the one `ajuster.py` writes in `profiles/`.

## The scripts

| Script | What it does |
|---|---|
| `dcp_ecrire.py` | writes and reads `.dcp` camera profiles (TIFF "IIRC" structure, DNG 1.7 tags). `--self-test` round-trips a profile and checks it with exiftool |
| `chaine_adobe.py` | my numpy model of Adobe's rendering chain (camera RGB to matrices, hue/sat map, exposure, look table, tone curve), after the DNG specification and the reference render of the DNG SDK, cross-checked with dcamprof. `--self-test` |
| `echantillons.py` | first batch: uniform 16 x 16 px blocks of camera RGB and of the Phocus export (and the camera JPEG) |
| `echantillons_passe2.py` | second batch: the same without the JPEG, for more lenses, ISO and warm light |
| `ajuster.py` | first fit: tone curve, forward matrix and 3D look table, with a free exposure gain per photo; one photo in four held out |
| `ajuster_v2.py` | second fit: per-photo BaselineExposure, correction from real Camera Raw renders, writes the `.dcp` |
| `valider_acr.py`, `acr_v2.py` | real Camera Raw renders through Photoshop (sidecar XMP with the profile forced and everything at zero), then measurements |
| `passe2.py` | conductor of the second batch: rounds of correction, held-out measurement, lens-by-lens study, the final report |
| `via_dcamprof.py` | the alternative route with dcamprof, kept for comparison |
| `adoucir_look.py` | versions 1.1 and 1.2: smooths the look table near gray to remove banding, and makes output brightness rise with input brightness in the brightest tones (rings around the sun). `ecrire <1.0 profile> <output>` rebuilds 1.2 with its default settings, `--sans-hl` gives 1.1. `--self-test` fails if the released profile breaks gradients through gray or lets brightness go down |

`--self-test` exists on every script. All run from this repository and `data/` except `valider_acr.py` (Photoshop, 3FR and installed profiles needed); `chaine_adobe.py` and `via_dcamprof.py` skip their dcamprof check when it is not installed.
