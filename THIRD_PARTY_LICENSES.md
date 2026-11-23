# Third-party material

| Item | Role | Source | License | In this repository? |
|---|---|---|---|---|
| Adobe `Adobe Standard` camera profile for `Hasselblad 100-22-Coated6` | `ColorMatrix1`, `ColorMatrix2` and the calibration illuminants (Standard Light A, D65) stored in the `.dcp` are copied from it unchanged. The `ForwardMatrix1/2`, the tone curve and the look table are computed for this profile. | Installed by Lightroom Classic / Camera Raw, copyright Adobe, Inc.; the profile carries the policy "Allow Copying" | Adobe's. I claim no rights on these numbers and do not put them under the MIT license | Only inside the `.dcp`, as the profile format requires. The profile file itself is not Adobe's file: it has its own tone curve, forward matrices and look table |
| Adobe DNG specification 1.7 and DNG SDK reference render | format of the profile; the rendering chain modeled in `chaine_adobe.py` follows the specification and the reference algorithms | [Adobe, Digital Negative](https://helpx.adobe.com/camera-raw/desktop/dng-and-file-formats/digital-negative.html) | Adobe's | No: `chaine_adobe.py` is a rewrite in numpy; no SDK code is copied |
| dcamprof (Anders Torger) | cross-check of the rendering model, and a first approach (`via_dcamprof.py`) | [github.com/Entropy512/dcamprof](https://github.com/Entropy512/dcamprof) (GitHub mirror) | GPL-3.0 | No: called as an external program, to install separately |
| numpy, scipy, rawpy, Pillow, OpenCV, colour-science, exiftool | dependencies of the scripts | their own projects | permissive or GPL-compatible, see each project | No: installed by the user |
| Phocus, HNCS | the reference rendering the profile approximates | Hasselblad | Hasselblad's | No Hasselblad software and no Phocus image file. `data/` holds block averages (16 x 16 px, uniform patches) measured on Phocus exports of my own photos |
| The figures `docs/figures/comparison.png` and `hero.png` | illustration | my photos, rendered by Phocus, the camera and Camera Raw | © Thomas Hammoudi, all rights reserved | Yes. They are not under the MIT license |

The measurement files in `data/` (`.npz`) hold block measurements taken from my own photographs, under CC BY 4.0 (see `data/README.md`). No image can be rebuilt from them.
