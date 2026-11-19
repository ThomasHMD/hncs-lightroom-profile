First public release of **HNCS**, a free Lightroom Classic / Camera Raw camera profile that reproduces the Hasselblad HNCS color of the X2D II 100C.

## Installation

1. Download `HNCS-Hasselblad-X2D-II.dcp` below (~28 KB).
2. Quit Lightroom Classic and copy the file into the **user** Camera Raw folder: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) or `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows).
3. Start Lightroom Classic and pick **HNCS** in the Profile browser. The README explains how to make it the default for the X2D II.

SHA-256: `6baec0c806b5e368a24243d8a7ba0a33d92194bfcac7d5c20f6c6ab7d40c9e82`

## What works

- Median ΔE2000 against Phocus of 1.56 as is (Adobe Standard: 2.51), on 41 photos kept out of the fitting, in real Camera Raw renders.
- Neutral grays stay neutral; the camera's automatic brightness (BaselineExposure) is applied by Lightroom as usual.

## Requirements

- Lightroom Classic or Camera Raw, Mac or Windows.
- An X2D II 100C (camera name `Hasselblad 100-22-Coated6`).

## Known limitations (v1.0.0)

- Weaker at ISO 3200 and above and in bright highlights.
- Three lenses tested (XCD 35-100E, 38V, 55V); Phocus lens corrections not reproduced; Phocus HDR not covered.
- Phocus's slightly warm neutrals are not carried by the profile.

## License

MIT for the tools and the profile, except the two color matrices copied from Adobe's own profile, the data in `data/` (CC BY 4.0) and the photos in `docs/figures/`. See [`LICENSE`](https://github.com/ThomasHMD/hncs-lightroom-profile/blob/main/LICENSE) and [`THIRD_PARTY_LICENSES.md`](https://github.com/ThomasHMD/hncs-lightroom-profile/blob/main/THIRD_PARTY_LICENSES.md).
