**HNCS 1.1** fixes faint banding in smooth, pale gradients, such as a sunset sky fading from blue to yellow near the horizon.

## What changed

- For nearly gray colors, the 3D color table of 1.0 changed abruptly from one hue to the next. A pale sky passing from blue to yellow goes through gray, so it swept through every hue in a few pixels and showed pink and green bands.
- 1.1 smooths that part of the table and halves the correction of nearly gray colors. Tone curve, matrices and saturated colors are unchanged.
- On the reported photo, the bands are gone, about as smooth as Adobe Standard.
- Accuracy against Phocus, on 16 of the 41 test photos re-rendered in Camera Raw, median ΔE2000: 1.03 for 1.1 and 1.05 for 1.0 with exposure tuned per photo; 1.21 and 1.30 as is.
- New: `tools/adoucir_look.py`, with a permanent banding check in its `--self-test`.

Thanks to the X2D user who reported it with a test file.

## Update from 1.0

1. Download `HNCS-Hasselblad-X2D-II.dcp` below.
2. Quit Lightroom Classic and replace the old file in the **user** Camera Raw folder: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) or `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows).
3. Restart Lightroom. The profile is still called **HNCS**: photos already set to it switch to 1.1 by themselves.

SHA-256: `ce6dc413962751856fd09e3076063d6a2941020f40a7fb1dfc08b5cf825fe03c`

## Known limitations

- Smooth gradients of vivid orange may still show slight banding (seen in the model only, not yet on a real photo).
- Weaker at ISO 3200 and above and in bright highlights; three lenses tested; Phocus lens corrections and HDR not covered.

## License

MIT for the tools and the profile, except the two color matrices copied from Adobe's own profile, the data in `data/` (CC BY 4.0) and the photos in `docs/figures/`. See [`LICENSE`](https://github.com/ThomasHMD/hncs-lightroom-profile/blob/main/LICENSE) and [`THIRD_PARTY_LICENSES.md`](https://github.com/ThomasHMD/hncs-lightroom-profile/blob/main/THIRD_PARTY_LICENSES.md).
