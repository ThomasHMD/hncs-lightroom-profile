**English** | [Français](README.fr.md)

# HNCS: Hasselblad X2D II color profile for Lightroom Classic

A free Adobe camera profile (`.dcp`) for Lightroom Classic and Camera Raw that reproduces the Hasselblad HNCS color of the X2D II 100C, so a 3FR looks like Phocus's rendering without opening Phocus. It is a camera profile, not a preset, and it works on Mac and Windows. Since version 2.0 the repository also carries an optional Lightroom Classic module that sets Exposure, Shadows and Highlights photo by photo (macOS only for now, see [Lightroom module](#lightroom-module-optional)).

<p align="center"><img src="docs/figures/hero.png" width="900" alt="HNCS for Lightroom: three X2D II photos, Phocus on the left half and Camera Raw with HNCS on the right half"></p>

<p align="center"><img src="docs/figures/comparison.png" width="900" alt="Five X2D II photos in four columns: Phocus (HNCS), the in-camera JPEG, Lightroom / Camera Raw with HNCS, and Camera Raw with Adobe Standard"></p>

*Five photos kept out of the fitting. Camera Raw at exposure 0, no adjustment of any kind, lens corrections off; the brightness of each photo is the one the camera writes in the 3FR. Phocus and the camera JPEG are shown as references.*

## Download

### ➜ [**HNCS-Hasselblad-X2D-II.dcp** (latest release)](https://github.com/ThomasHMD/hncs-lightroom-profile/releases/latest/download/HNCS-Hasselblad-X2D-II.dcp)

28 KB, for the X2D II 100C. **First-generation X2D 100C (2022)?** Use [**HNCS-Hasselblad-X2D-100C.dcp**](https://github.com/ThomasHMD/hncs-lightroom-profile/releases/latest/download/HNCS-Hasselblad-X2D-100C.dcp) instead: same profile, keyed to the X2D's own camera name (see [Use it](#use-it)). All versions are in the [Releases](https://github.com/ThomasHMD/hncs-lightroom-profile/releases). The tools that fitted versions 1.x are in this repository, under the MIT license (see [License](#license)).

Optional, for Lightroom Classic on macOS: [**HNCS-Lightroom-module.zip**](https://github.com/ThomasHMD/hncs-lightroom-profile/releases/latest/download/HNCS-Lightroom-module.zip) (9 KB), a module that adjusts Exposure, Shadows and Highlights photo by photo (see [Lightroom module](#lightroom-module-optional)).

## What's new

### 2.0: smoother colors, much more robust when you push the settings

Version 2.0 is an improved profile. Accuracy against Phocus stays the same as 1.2 (median ΔE2000 1.03 against 1.04, on 34 photos kept out of the 1.2 fitting). What changes is the color table, which is much more regular:

- **It holds up far better under local adjustments.** With a mask on a sky and strong changes of white balance, hue or saturation, 1.2 could break smooth gradients into patches or bands (an X2D user reported it). I counted the pixels of a sky where a gradient breaks after an adjustment, on 13 warm and blue skies and 9 adjustments each (109 cases): median 16 per thousand for 2.0, 137 for 1.2, and 16 for Camera Raw's default profile. One case stays a little worse than 1.2: adding saturation (24 against 15 per thousand).
- **The color table is smoother**: the largest jump between two neighboring entries is 3.4 against 14.2 in 1.2.
- **Not better everywhere.** Against the camera's own JPEG it is not closer than 1.2 (2.31 against 2.33, 8 photos). Photo by photo against Phocus it is closer on 17 of 34, clearly closer (more than 0.3) on 5 and clearly farther on 9. As is, without any exposure correction, it is a little farther from Phocus (1.35 against 1.26). Details in [Accuracy](#accuracy).
- **Same name, slightly different colors.** The profile is still called **HNCS**, so photos already set to it switch to 2.0 by themselves. If you prefer the old rendering, 1.2.1 stays downloadable in the [Releases](https://github.com/ThomasHMD/hncs-lightroom-profile/releases).
- **New: an optional Lightroom module**, see [Lightroom module](#lightroom-module-optional).
- The `HNCS-Hasselblad-X2D-100C.dcp` variant is rebuilt from 2.0 the same way as before. It was not measured on X2D files.

The figures and the first table below were made with 1.0. The scripts in `tools/` are those of versions 1.x.

<p align="center"><img src="docs/figures/versions.png" width="900" alt="A simulated sunset through the color table of HNCS 1.0, 1.1 and 1.2: the dark arc fades in 1.1, the ring around the sun is gone in 1.2"></p>

### 1.2: no more ring around the sun

In backlit sunsets, version 1.1 could draw a darker orange ring around the sun. The cause was the top of the 3D color table: for very bright yellow-orange tones, it halved the brightness, so the sky got darker as it got closer to the sun, then jumped to white. In 1.2, brightness always rises with the light, everywhere in the table. I checked it on six backlit sunsets sent by an X2D user. Nothing else changed: on the same 16 test photos as for 1.1, accuracy against Phocus is identical (median ΔE2000 1.21 as is), and the bands fix of 1.1 is kept. The self-test now also refuses a profile whose brightness goes down anywhere.

### 1.1: fix for banding in skies

Version 1.0 could show faint pink and green bands in smooth, pale gradients, typically a sunset sky that fades from blue to yellow near the horizon (thanks to the X2D user who reported it with a test file). The cause was the profile's 3D color table: for nearly gray colors, its correction changed abruptly from one hue to the next. A pale sky going from blue to yellow passes through gray, so it sweeps through every hue within a few pixels, and each hue got a slightly different correction.

Version 1.1 smooths that part of the table and halves the correction of nearly gray colors. Everything else (tone curve, matrices, saturated colors) is unchanged. On the reported photo, the bands are gone and the sky is about as smooth as with Adobe Standard. Accuracy against Phocus did not get worse: on 16 of the 41 test photos, re-rendered in Camera Raw, the median ΔE2000 is 1.03 for 1.1 and 1.05 for 1.0 with exposure tuned per photo, and 1.21 and 1.30 as is. A permanent check now runs synthetic gradients through gray in `tools/adoucir_look.py --self-test`.

If you installed an earlier version, replace the file with the new one (same name, same place) and restart Lightroom. The profile keeps its name, **HNCS**, so photos already set to it switch to the new version by themselves.

## Install

The profile goes in the **user** folder of Camera Raw. Not in the application folder, not in the system folder.

1. Quit Lightroom Classic.
2. Copy the `.dcp` for your camera (`HNCS-Hasselblad-X2D-II.dcp`, or `HNCS-Hasselblad-X2D-100C.dcp` for the first-generation X2D) into:
   - **macOS**: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/`
     (in the Finder: Go ▸ Go to Folder…, then paste the path; the `Library` folder is hidden)
   - **Windows**: `%APPDATA%\Adobe\CameraRaw\CameraProfiles\`
     (paste it in the Explorer address bar; it is `C:\Users\<your-name>\AppData\Roaming\Adobe\CameraRaw\CameraProfiles\`)
3. Start Lightroom Classic again.

Why this folder: the system folders (`/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` on macOS, `C:\ProgramData\Adobe\CameraRaw\CameraProfiles\` on Windows) hold Adobe's own profiles and are managed by Adobe's installer and updates, which can rewrite them. The user folder belongs to you: Lightroom reads it, and an update does not touch it. After a major Lightroom or Camera Raw update, check that the profile is still listed. If it is not, the file is still in the folder: restart Lightroom first, and some users report that resetting its preferences brings third-party profiles back.

Copying the file by hand, as above, is the method I tested.

## Use it

1. Open a 3FR from the X2D II in the Develop module.
2. Basic panel ▸ **Profile** ▸ Browse (the four-square icon). The profile is called **HNCS** and sits in the **Profiles** group, below Camera Matching (not under Adobe Raw). The **Amount** slider at the top of the browser lets you dial it down. Click the star to make it a favorite, so it shows in the Profile drop-down.
3. The profile only appears for files of the camera it is keyed to. `HNCS-Hasselblad-X2D-II.dcp` is keyed to Adobe's camera name `Hasselblad 100-22-Coated6` (X2D II 100C): I tested it on that camera only. `HNCS-Hasselblad-X2D-100C.dcp` is the same profile keyed to `Hasselblad 100-20-Coated6` (first-generation X2D 100C, same sensor). It reuses the X2D II fit and was **not measured on X2D files**: one X2D user reports that it loads and works. If you own both cameras, both files can sit in the same folder: each only shows for its own camera.

### Make it the default for the X2D II

1. On one X2D II photo, choose HNCS as above.
2. In the Presets panel, right-click or use the **+** menu ▸ **Create Preset…**. Name it `HNCS`, click **Check None**, tick only **Treatment & Profile**, create.
3. Lightroom Classic ▸ Preferences (Edit ▸ Preferences on Windows) ▸ **Presets** tab ▸ **Raw Defaults**. Tick **Override global setting for specific cameras**, pick **Hasselblad X2D II 100C** in the **Camera:** list, then in **Default:** choose **Preset** and your `HNCS` preset.

The Camera list is built from the raw photos already in your catalog, so import at least one X2D II photo first. Do not pick **Camera Settings** for this: it only honors styles applied in the camera and does not know about this profile. The default applies to photos imported afterwards; for photos already in the catalog, apply the preset to them. Menu names are those of the Lightroom Classic app itself; Adobe's documentation is [Set up default settings for raw images](https://helpx.adobe.com/lightroom-classic/desktop/help/raw-defaults.html).

## Brightness

HNCS also sets the brightness of each photo automatically. The camera writes that decision in the 3FR (the `BaselineExposure` tag: 0, +1 or +2 EV depending on the shot), and Lightroom and Camera Raw already apply it by themselves. So brightness follows Phocus's, roughly. On the 41 images I kept aside for testing, the remaining difference to Phocus is small, typically within ±0.2 EV (median −0.03 EV, the extremes are −0.57 and +0.20 EV). Photos with a +1 or +2 EV tag come out about 0.2 EV lighter than Phocus. A small touch on the Exposure slider is therefore possible, and it is sometimes needed.

## Lightroom module (optional)

**Why a module on top of the profile?** The camera decides a brightness for each photo. When it shoots RAW + JPEG at ISO 100 or 200, it often lifts the picture digitally by 1 or 2 stops (EV), and it also decides how much to lift the shadows and pull back the highlights. Those decisions are written in the 3FR. A profile is the same recipe for every photo: it cannot change from one photo to the next. The module reads the camera's decisions in each file and sets Exposure, Shadows and Highlights photo by photo, together with the profile, in a single operation you can undo.

**What it brings**, measured in Camera Raw against Phocus (median ΔE2000, photos kept out of the tuning, profile 2.0):

| Photos | Without the module | With the module |
|---|---|---|
| RAW + JPEG lifted by 1 or 2 EV (8 photos) | 3.86 | **2.20** |
| RAW only, ISO 6400 and above (14 photos) | 3.11 | **2.22** |
| All other photos (RAW only, below ISO 6400) | 1.18 | left as they are |

The samples are small: take these figures as an indication. They were measured in Camera Raw (Photoshop), not in Lightroom itself. The ISO 6400 threshold was set on those same 14 photos (at ISO 3200 the correction made 5 photos out of 6 worse), so that line is not an out-of-sample figure, and no photo between ISO 3200 and 6400 was available.

**Install** (macOS, Lightroom Classic):

1. Install `exiftool` (`brew install exiftool`, or the installer from exiftool.org) and the HNCS profile (see [Install](#install)).
2. Download [`HNCS-Lightroom-module.zip`](https://github.com/ThomasHMD/hncs-lightroom-profile/releases/latest/download/HNCS-Lightroom-module.zip), unzip it, and put the folder `reglages-x2d.lrplugin` somewhere you will keep it (the same folder is in [`plugin/`](plugin/)).
3. In Lightroom Classic: **File ▸ Plug-in Manager… ▸ Add**, choose the `reglages-x2d.lrplugin` folder, then **Done**. The module shows a green dot, "Installed and running".
4. If `exiftool` is not in `/opt/homebrew/bin`, `/usr/local/bin` or `/usr/bin`: **Library ▸ Plug-in Extras ▸ Réglages du module (chemin d'exiftool)** and type its path.

**Use it.** Select photos in the Library, then **Library ▸ Plug-in Extras ▸ Appliquer profil et réglages X2D II** (the same menu is under File ▸ Plug-in Extras). Only 3FR files of the X2D II are processed; other photos are skipped and counted. With no selection, nothing happens. A window sums up what was done. The module writes in the Lightroom catalog only, never in your files, and does not touch the other settings (white balance, sharpening, crop). The menus and messages are in French for now.

| Photo | Profile | Exposure | Shadows | Highlights |
|---|---|---|---|---|
| RAW only (the camera decided nothing), ISO below 6400 | HNCS | unchanged | unchanged | unchanged |
| RAW only, ISO 6400 or more | HNCS | −0.15 | 0 | 0 |
| RAW + JPEG, camera lift about 0 EV | HNCS | +0.05 | +10 | −5 |
| RAW + JPEG, camera lift about 1 EV | HNCS | −0.20 | +5 | −20 |
| RAW + JPEG, camera lift about 2 EV | HNCS | −0.10 | 0 | −50 |

**Undo**: **Edit ▸ Undo "Réglages X2D II (HNCS)"** puts the profile and the three sliders back as they were, for all the photos at once.

**State of the module.** I used it in Lightroom Classic on macOS, on 3 RAW + JPEG photos lifted by 2 EV: the profile and the sliders were applied as expected. Not tried yet in Lightroom: RAW-only photos and mixed selections (the rule itself was checked outside Lightroom). **Windows: not tested**, the module stops with a message instead of guessing. The rule was fixed on a few photos (11 with camera decisions kept aside), and an old catalog with an old process version may ignore some sliders.

## Accuracy

Differences are measured against a Phocus export (default settings, SDR) of the same 3FR, in ΔE2000 (about 1: hardly visible; 2 to 3: visible side by side). For scale, Phocus and the camera's own JPEG differ from each other by about 2 (median). The measurements use real Camera Raw renders (see [How it was made](#how-it-was-made)), on **41 photos kept out of the fitting**, from 3 lenses (XCD 35-100E, 38V, 55V), at the center of the frame, on uniform patches.

| Median ΔE2000 / 90th percentile | HNCS | Adobe Standard |
|---|---|---|
| All 41 photos, Camera Raw as is (exposure 0) | **1.56** / 4.45 | 2.51 / 5.58 |
| All 41, with exposure tuned for each photo | **1.23** / 3.24 | 1.87 / 4.18 |
| Warm light under 4500 K (10 photos), as is | **1.56** / 4.75 | 3.22 / 5.83 |
| ISO 3200 and above (4 photos), as is | **3.67** / 5.47 | 4.48 / 6.29 |
| Bright areas (24 photos), as is | **2.35** / 6.37 | 2.88 / 6.80 |

The table above and the figures were made with version 1.0; 1.1 and 1.2 only differ in pale, nearly gray colors and in very bright warm tones (see [What's new](#whats-new)). Version 2.0 is measured separately, below.

Tested since then:

- **2.0**, real Camera Raw renders, 34 photos kept out of the 1.2 fitting, against Phocus (median ΔE2000 with exposure tuned per photo; 1.2 in brackets): all 1.03 (1.04); near-neutral colors 0.77 (0.87); saturated colors 1.69 (1.80); bright areas 1.14 (1.10); warm light under 4500 K 1.31 (1.13). As is, without exposure correction: 1.35 (1.26). Against the camera's JPEG, 8 photos kept aside: 2.31 (2.33). Under a sky mask: see [What's new](#whats-new).
- **1.1 and 1.2**: re-rendered on 16 of the 41 photos. Median ΔE2000 1.21 as is and 1.03 with exposure tuned per photo; 1.0 on the same 16 photos: 1.30 and 1.05.
- **Skin tones**: 3 photos with people (2 of them kept out of the fitting), 1,617 patches on faces, necks and hands. Median 1.10 for HNCS, 2.60 for Adobe Standard (90th percentile 2.81 and 4.71).
- **Bright warm skies**: 33 more photos with sunsets and bright highlights (6 of them from an X2D user), exported from Phocus, plus 16 of the test photos as a control. I used them to try a refit of the bright, saturated part of the color table: it brought the photos used for the refit closer to Phocus but moved the other photos further away (median 1.97 before, 2.13 to 2.31 after). So 1.2 keeps its table: a fixed profile cannot do better there.

Limits, as they are:

- **High ISO** (3200 and above) and **bright highlights** are the weak spots: the gap to Phocus stays large there. Only 4 photos at ISO 3200 and above were kept aside, so that number is not solid.
- Phocus renders neutral grays slightly warm. A camera profile cannot carry that without disturbing white balance, so HNCS keeps neutrals neutral. If you like the Phocus warmth, warm the white balance a little.
- Phocus also corrects distortion and vignetting of the lens. This profile does not; the measurements were made with Camera Raw's lens corrections off.
- Each camera carries a factory calibration in its 3FR files, which Lightroom already applies (I checked by editing it in copies of files), so the profile stays valid from one body to another; I could check this on one body only. What Lightroom does not take over is the lens-specific color shading toward the edges of the frame that the camera corrects in its own JPEG: neither a profile nor the module can carry it.
- The Phocus **HDR** rendering is not covered.
- Warm sunset skies come out a little less saturated and lighter near the sun than in Phocus or the camera's own HEIC. Phocus keeps those yellows; Camera Raw's own highlight processing loses some of them, with every profile (Adobe Standard and Adobe Color lose more), and by a different amount in each photo, so a fixed profile cannot make up for it. Lower Highlights and add a little Vibrance if you want them closer.
- Smooth gradients of vivid orange may still show slight banding in places: the color table is still uneven at medium saturation. Not seen yet on a real photo.
- Three lenses were tested. Others (XCD 90V, 25V, 20…) are untested, and Phocus lifts brightness differently depending on the lens.
- The measurements were made on one body and by sampling uniform patches. Fine texture was not measured; skin tones only on the 3 photos above.
- They were made with Camera Raw driven from Photoshop, which is the engine Lightroom uses, not with Lightroom Classic itself.

The tools write these reports themselves, so they can be regenerated with your own files (see [`tools/README.md`](tools/README.md)).

## How it was made

I exported pairs of files: the 3FR, and the same photo from Phocus at its default HNCS settings. From 170 photos (128 for fitting, 42 kept aside, of which 41 could be rendered in Camera Raw; three lenses, ISO 50 to 25600, daylight and warm light), I fitted versions 1.x inside Adobe's own rendering chain (DNG specification 1.7): a tone curve, a small correction of the color matrix, and a 3D color table (hue, saturation, value), with neutrals left untouched. Then I corrected it in two rounds from **real Camera Raw renders**, because my model of the chain differed from Camera Raw by about 1.6 ΔE, mostly in highlights. One photo in four, chosen by lens, was never used for fitting; the table above is on those. (12 of these 41 were also used to choose between the correction rounds, a small bias; the difference between the two last rounds was negligible.)

The tools of versions 1.x are in [`tools/`](tools/) (Python, comments in French), with a [README](tools/README.md) that says what each script does and what it needs. The measurements versions 1.x were fitted on are published in [`data/`](data/README.md) (CC BY 4.0), so the fitting scripts run from this repository.

I built it with the help of Claude Code (Anthropic's coding assistant), which wrote much of the Python in `tools/` under my direction. The method, the choices and the measurements are mine, and I checked the results in real Camera Raw renders.

## Credits and prior art

- [u/ubiquitousuk](https://www.reddit.com/user/ubiquitousuk/) (Reddit, r/hasselblad) had the idea of the first-generation X2D variant: changing the profile's camera name to `100-20-Coated6`. They tried it on their own X2D files and sent me the working file; `tools/variante_x2d.py` rebuilds it from the X2D II profile.
- [Konrad Michels, "What a Lightroom Camera Profile Can and Cannot Reproduce from Phocus"](https://blog.tonalphoto.com/lightroom-camera-profile-phocus-color/) (Tech Behind the Frame): same approach, fitting a Lightroom camera profile to Phocus renders of the X2D II. His profile is now a free download too: [Rockfish X2D II](https://github.com/kmichels/rockfish-x2d-ii) (profile under CC BY 4.0, build tools under MIT). We compare our measurements and are working together on per-lens corrections.
- [dcamprof](https://github.com/Entropy512/dcamprof) (GitHub mirror) by Anders Torger, used to cross-check my rendering model and as a first approach. It is GPL-3.0 and is not included: my scripts only call it as an external program. I kept my own fitting, which measured better in Camera Raw.
- The profile structure follows Adobe's DNG specification. The colour matrices come from Adobe's own profile (see [License](#license)).

## License

- **The tools and the documentation**: MIT ([`LICENSE`](LICENSE)).
- **The profile** (the tone curve, the 3D color table and the forward matrices): also MIT. The two color matrices (`ColorMatrix1`, `ColorMatrix2`) and the calibration illuminants stored in the file are copied unchanged from the `Adobe Standard` profile of the same camera, which Adobe distributes with Lightroom (the profile carries the tag "Allow Copying"). I claim no rights on them. Details: [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- **The data** (`data/`, the block measurements): CC BY 4.0, © Thomas Hammoudi. Credit me and link this repository. Details in [`data/README.md`](data/README.md).
- **The Lightroom module** (`plugin/`): MIT, like the tools.
- **The photos** (the two figures in `docs/figures/`): © Thomas Hammoudi, all rights reserved. They are not under the licenses above, which cover the code, the profile, the data and the analyses.

## Disclaimer

Independent project, **not affiliated with or endorsed by** Hasselblad or Adobe. "Hasselblad", "X2D", "Phocus" and "HNCS" (Hasselblad Natural Colour Solution) are trademarks of their owners, as are "Adobe", "Lightroom" and "Camera Raw". This repository contains no Hasselblad software and no Phocus image file: only a camera profile that approximates a rendering, and block averages (16 x 16 px, uniform patches) measured on Phocus exports of my own photos. Use at your own risk.
