# Data

The measurements versions 1.x of the profile were fitted on. With these two files the fitting scripts in [`../tools/`](../tools/) run from this repository, without any raw file of mine. Everything here comes from my own photographs, taken with a Hasselblad X2D II 100C.

| File | Size | Images | Blocks | What it is |
|---|---|---|---|---|
| `samples-pass1.npz` | 4.2 MB | 33 (`B0000583` to `B0000711`, XCD 55V, ISO 50 to 200) | 124 414 | first batch: 3FR, Phocus export and camera JPEG of the same photo |
| `samples-pass2.npz` | 11.7 MB | 146 (`B0000001` to `B0002409`, XCD 55V, 38V and 35-100E, ISO 50 to 25600) | 440 441 | second batch: 3FR and Phocus export, no JPEG |

Both are NumPy archives (`numpy.load(path)`, no pickle needed). 170 of the 179 images were kept for the fit (9 had fewer than 300 usable blocks).

## What a "block" is

For each photo I cut the frame into blocks of 16 x 16 pixels (full size) and kept only the **uniform** ones: relative standard deviation under 0.04 on every source, no clipping, near the center of the frame, up to 4 000 per image (1 500 or more for the leafy scenes of the second batch, with a looser texture limit). Each block is stored as one row: the average of the camera data and the average of the Phocus export. **No photo can be rebuilt from this**: it is a list of numbers for uniform patches and their positions, not an image.

## Fields

Per block (one row each; `N` is the number of blocks of the file):

| Field | Shape | Meaning |
|---|---|---|
| `cam_rgb` | N x 3 | camera RGB, linear, raw: black level subtracted, 1 = saturation, half-size demosaic, no color matrix, no white balance |
| `phocus_xyz` | N x 3 | Phocus export (16-bit TIFF, Adobe RGB, default HNCS settings, SDR) converted to CIE XYZ, linear, D50 white point |
| `jpeg_xyz` | N x 3 | pass 1 only: the camera's own JPEG (Display P3), same XYZ D50 |
| `by`, `bx` | N | position of the block in the export, in units of 16 pixels (row, column) |
| `image` | N | index of the photo in `noms` and in the per-image fields |
| `cv_raw`, `cv_phocus` | N | pass 2 only: relative standard deviation inside the block, raw and Phocus (texture; used to weight the fit) |
| `rad2` | N | pass 2 only: squared distance to the center of the frame, in fractions of the frame size (the blocks are taken at `rad2` < 0.05, relaxed for leafy scenes) |

Per image (one entry each, same order as `noms`):

| Field | Meaning |
|---|---|
| `noms` | file name without extension, my Hasselblad numbering (`B0000583`). No path |
| `wb_as_shot` | white balance multipliers of the camera (R, G, B, G2), as shot |
| `blocs_par_image_total` | number of uniform blocks found in the photo before the cap per image |
| `objectif` | lens (`XCD 55V`, `XCD 38V`, `XCD 35-100E`) |
| `focale` | focal length in mm (as written in the 3FR) |
| `iso` | ISO |
| `baseline_exposure` | the `BaselineExposure` tag of the 3FR, in EV (0, about +1 or +2): the brightness decision of the camera, which Camera Raw applies by itself |
| `image_width`, `image_height` | size in pixels of the Phocus export (11656 x 8742, a few cropped by Phocus) |
| `comp`, `temp_K` | pass 2 only: exposure compensation in EV, and the color temperature estimated from the as-shot white balance, in kelvin |
| `etage` | pass 2 only: step of the relaxation scale at which the image reached enough blocks (0 = the strictest limits) |
| `note` | the same description in one sentence |

Field names are in French where I wrote them first (`noms`, `objectif`, `focale`); the scripts read them as they are.

## License

The data are released under **CC BY 4.0**, © Thomas Hammoudi: you may use, share and adapt them, including commercially, if you credit me and link this repository. The code, the profile and the documentation of the repository stay under the MIT license ([`../LICENSE`](../LICENSE)). The Phocus numbers are measurements of the output of Hasselblad's software on my own files; they contain no image and no part of the software.

## Use

```
python3 tools/ajuster.py --sans-planche    # refits the first profile from samples-pass1.npz (about 2 minutes)
python3 tools/passe2.py donnees            # the 170 images, by lens, ISO and light
python3 tools/passe2.py --self-test
```

See [`../tools/README.md`](../tools/README.md) for what runs on these files alone and what needs the raw photos or Photoshop.
