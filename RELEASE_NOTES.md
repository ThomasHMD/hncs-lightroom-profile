# v2.0.0: smoother colors, much more robust profile, new Lightroom module / profil plus régulier et bien plus robuste, nouveau module Lightroom

*🇫🇷 Version française plus bas.*

**HNCS 2.0** is an improved profile: same accuracy against Phocus as 1.2, a much more regular color table, and far better behavior when you push the settings or work under a mask (skies). It also comes with an optional **Lightroom Classic module** (macOS).

## What changed

- **Profile 2.0**: median ΔE2000 against Phocus 1.03 (1.2: 1.04, 34 photos kept out of the 1.2 fitting). Sky under a mask with strong adjustments: 16 broken-gradient pixels per thousand against 137 for 1.2 (13 skies, 109 cases), as good as Camera Raw's default profile. Largest jump in the color table 3.4 against 14.2. Not better against the camera's JPEG (2.31 against 2.33), and a little farther from Phocus as is, without exposure correction (1.35 against 1.26).
- **New: Lightroom module** (`HNCS-Lightroom-module.zip`, optional, macOS only for now, needs exiftool). It reads the brightness decisions the camera writes in each 3FR and sets the profile, Exposure, Shadows and Highlights photo by photo, in one undoable step. In Camera Raw against Phocus (small samples, profile 2.0): RAW + JPEG lifted by 1 or 2 EV 3.86 to 2.20, RAW only at ISO 6400 and above 3.11 to 2.22; other photos left alone. Details in the README.
- The X2D 100C variant is rebuilt from 2.0 (not measured on X2D files).
- The profile keeps its name **HNCS**: photos already set to it switch to 2.0. 1.2.1 stays available in the Releases.

## Update

1. Download `HNCS-Hasselblad-X2D-II.dcp` below (or `HNCS-Hasselblad-X2D-100C.dcp` for the first-generation X2D).
2. Quit Lightroom Classic and replace the old file in the **user** Camera Raw folder: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) or `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows).
3. Restart Lightroom. For the module, see the README.

SHA-256:
- `HNCS-Hasselblad-X2D-II.dcp`: `112eb31a989d0014e6f5d943af6a210ec62440c3bed62ef7cc0414f34e508dcc`
- `HNCS-Hasselblad-X2D-100C.dcp`: `7a0c9da9a09577ab6725e2ace011f5c017991387926051d9b78e654df77645f8`
- `HNCS-Lightroom-module.zip`: `e6bb1bcad614ba7578e8a7c3263ac0f46b3383e747ce69328982f815daeb5e45`

## Known limitations

- Same limits as before: ISO 3200 and above, bright highlights, three lenses tested, Phocus lens corrections and HDR not covered.
- Module: tried on 3 photos in Lightroom Classic on macOS; Windows not tested; menus in French; small samples; not remeasured with 2.0.

---

## 🇫🇷 En français

**HNCS 2.0** est un profil amélioré : même fidélité à Phocus que la 1.2, une table de couleurs bien plus régulière, et un comportement bien meilleur quand on pousse les réglages ou qu'on retouche sous un masque (ciels). Il est accompagné d'un **module Lightroom Classic** facultatif (macOS).

## Ce qui change

- **Profil 2.0** : ΔE2000 médian contre Phocus 1,03 (1.2 : 1,04, 34 photos tenues hors de l'ajustement de la 1.2). Ciel sous masque avec de forts réglages : 16 pixels pour mille où un dégradé casse contre 137 pour la 1.2 (13 ciels, 109 cas), autant que le profil par défaut de Camera Raw. Plus grand saut dans la table de couleurs 3,4 contre 14,2. Pas meilleur contre le JPEG du boîtier (2,31 contre 2,33), et un peu plus éloigné de Phocus tel quel, sans correction d'exposition (1,35 contre 1,26).
- **Nouveau : module Lightroom** (`HNCS-Lightroom-module.zip`, facultatif, macOS seulement pour l'instant, demande exiftool). Il lit les décisions de luminosité que le boîtier écrit dans chaque 3FR et règle le profil, Exposition, Ombres et Hautes lumières photo par photo, en une seule opération annulable. Dans Camera Raw contre Phocus (petits échantillons, profil 2.0) : RAW + JPEG remontés de 1 ou 2 IL 3,86 à 2,20, RAW seul à ISO 6400 et plus 3,11 à 2,22 ; les autres photos ne sont pas touchées. Détails dans le README.
- La variante X2D 100C est refaite à partir de la 2.0 (non mesurée sur des fichiers de X2D).
- Le profil garde son nom **HNCS** : les photos qui l'utilisent déjà passent à la 2.0. La 1.2.1 reste disponible dans les Releases.

## Mise à jour

1. Télécharger `HNCS-Hasselblad-X2D-II.dcp` ci-dessous (ou `HNCS-Hasselblad-X2D-100C.dcp` pour le X2D de première génération).
2. Quitter Lightroom Classic et remplacer l'ancien fichier dans le dossier **utilisateur** de Camera Raw : `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` (macOS) ou `%APPDATA%\Adobe\CameraRaw\CameraProfiles\` (Windows).
3. Relancer Lightroom. Pour le module, voir le README.

SHA-256 :
- `HNCS-Hasselblad-X2D-II.dcp` : `112eb31a989d0014e6f5d943af6a210ec62440c3bed62ef7cc0414f34e508dcc`
- `HNCS-Hasselblad-X2D-100C.dcp` : `7a0c9da9a09577ab6725e2ace011f5c017991387926051d9b78e654df77645f8`
- `HNCS-Lightroom-module.zip` : `e6bb1bcad614ba7578e8a7c3263ac0f46b3383e747ce69328982f815daeb5e45`

## Limites connues

- Mêmes limites qu'avant : ISO 3200 et plus, hautes lumières vives, trois objectifs testés, corrections d'objectif et HDR de Phocus non couverts.
- Module : essayé sur 3 photos dans Lightroom Classic sous macOS ; Windows non testé ; menus en français ; petits échantillons ; non remesuré avec la 2.0.
