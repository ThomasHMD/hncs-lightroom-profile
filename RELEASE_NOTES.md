*🇫🇷 Version française plus bas.*

**HNCS 1.2.1** adds a variant for the **first-generation Hasselblad X2D 100C** (2022). The profile itself is unchanged.

## What changed

- New file `HNCS-Hasselblad-X2D-100C.dcp`: the same profile, keyed to Adobe's camera name `Hasselblad 100-20-Coated6` (the X2D) instead of `100-22-Coated6` (the X2D II). Same sensor, same color matrices: only the camera name differs. `tools/variante_x2d.py` rebuilds it from the X2D II profile.
- **Not measured on X2D files.** It reuses the fit made on X2D II photos. One X2D user reports that it loads and works.
- `HNCS-Hasselblad-X2D-II.dcp` is unchanged.

Thanks to [u/ubiquitousuk](https://www.reddit.com/user/ubiquitousuk/) (r/hasselblad), who had the idea and tried it on their X2D files.

## Install

Copy the `.dcp` for your camera into the **user** Camera Raw folder: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) or `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows). Restart Lightroom Classic. If you own both cameras, both files can sit in the same folder.

SHA-256:
- `HNCS-Hasselblad-X2D-II.dcp`: `04415637dc38e732518e17fe46f0d6fb9d93b69773c51d619a45094988d9f3d5`
- `HNCS-Hasselblad-X2D-100C.dcp`: `ce60386cca0be83cefc866718a0d5c0a1604e46415e475bb2b189d8150ba8dc1`

---

## 🇫🇷 En français

**HNCS 1.2.1** ajoute une variante pour le **Hasselblad X2D 100C de première génération** (2022). Le profil lui-même ne change pas.

## Ce qui change

- Nouveau fichier `HNCS-Hasselblad-X2D-100C.dcp` : le même profil, associé au nom d'appareil d'Adobe `Hasselblad 100-20-Coated6` (le X2D) au lieu de `100-22-Coated6` (le X2D II). Même capteur, mêmes matrices de couleur : seul le nom d'appareil diffère. `tools/variante_x2d.py` le reconstruit à partir du profil du X2D II.
- **Non mesuré sur des fichiers de X2D.** Il reprend l'ajustement fait sur des photos du X2D II. Un utilisateur de X2D signale qu'il se charge et fonctionne.
- `HNCS-Hasselblad-X2D-II.dcp` ne change pas.

Merci à [u/ubiquitousuk](https://www.reddit.com/user/ubiquitousuk/) (r/hasselblad), qui a eu l'idée et l'a essayé sur ses fichiers de X2D.

## Installation

Copiez le `.dcp` de votre boîtier dans le dossier **utilisateur** de Camera Raw : `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) ou `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows). Relancez Lightroom Classic. Si vous avez les deux boîtiers, les deux fichiers peuvent cohabiter dans le même dossier.
