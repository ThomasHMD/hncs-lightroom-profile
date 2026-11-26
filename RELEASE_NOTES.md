# v2.1.0: exposure correction per lens in the Lightroom module / correction d'exposition par objectif dans le module Lightroom

*🇫🇷 Version française plus bas.*

**The profile does not change** (still 2.0, same files, same checksums). Only the optional **Lightroom Classic module** goes to **1.1.0**.

## What changed

- For photos with no camera brightness decisions in the file and ISO below 6400, the module now sets **Exposure only**, by lens. Adobe's lens profile brightens the edges more than Phocus does, so these photos came out a little too light.
- Two columns, picked from the photo's *Enable Profile Corrections* setting (unknown = "off" column). Measured on my photos: XCD 55V −0.15 / −0.05 (on / off), 38V −0.20 / −0.05, 35-100E −0.05 / −0.03. Other lenses: small values from a measurement exchange with another X2D II photographer; unknown lens: nothing changes.
- On the 41 photos kept out of the fitting, with lens corrections on: closer to Phocus than module 1.0 on 24, the same on 14, farther on 3; median ΔE2000 2.01 to 1.49. With lens corrections off, no proven gain (1.41 to 1.40).
- **The module now overwrites the Exposure slider** of those photos (Edit ▸ Undo puts it back).
- Documentation fix: the camera writes its brightness decisions in the 3FR only when a JPEG or an HDR HEIF is recorded with the RAW.
- Tried in Lightroom Classic on 8 photos, lens corrections on and off, Undo checked.

## Update

Download `HNCS-Lightroom-module.zip`, replace the `reglages-x2d.lrplugin` folder you use, and reload the module in File ▸ Plug-in Manager. The profile files are unchanged.

SHA-256:
- `HNCS-Hasselblad-X2D-II.dcp`: `112eb31a989d0014e6f5d943af6a210ec62440c3bed62ef7cc0414f34e508dcc`
- `HNCS-Hasselblad-X2D-100C.dcp`: `7a0c9da9a09577ab6725e2ace011f5c017991387926051d9b78e654df77645f8`
- `HNCS-Lightroom-module.zip`: `62bde66c7318eea6bfaa24e5deba857da9c03677a42376ef8b26899888e3e7fb`

---

## 🇫🇷 En français

**Le profil ne change pas** (toujours la 2.0, mêmes fichiers, mêmes sommes de contrôle). Seul le **module Lightroom Classic** facultatif passe en **1.1.0**.

## Ce qui change

- Pour les photos sans décisions de luminosité du boîtier dans le fichier et sous ISO 6400, le module règle maintenant **l'Exposition seulement**, selon l'objectif. Le profil d'objectif d'Adobe éclaircit les bords plus que Phocus : ces photos sortaient un peu trop claires.
- Deux colonnes, choisies d'après le réglage *Activer les corrections de profil* de la photo (inconnu = colonne « coupées »). Mesuré sur mes photos : XCD 55V −0,15 / −0,05 (actives / coupées), 38V −0,20 / −0,05, 35-100E −0,05 / −0,03. Autres objectifs : petites valeurs issues d'un échange de mesures avec un autre photographe de X2D II ; objectif inconnu : rien ne change.
- Sur les 41 photos tenues hors de l'ajustement, corrections d'objectif actives : plus proche de Phocus que le module 1.0 sur 24, égal sur 14, plus éloigné sur 3 ; ΔE2000 médian de 2,01 à 1,49. Corrections coupées : aucun gain prouvé (1,41 à 1,40).
- **Le module écrase maintenant le curseur Exposition** de ces photos (Édition ▸ Annuler le remet).
- Correction de la documentation : le boîtier n'écrit ses décisions de luminosité dans le 3FR que lorsqu'un JPEG ou un HEIF HDR est enregistré avec le RAW.
- Essayé dans Lightroom Classic sur 8 photos, corrections d'objectif actives et coupées, annulation vérifiée.

## Mise à jour

Téléchargez `HNCS-Lightroom-module.zip`, remplacez le dossier `reglages-x2d.lrplugin` que vous utilisez, et rechargez le module dans Fichier ▸ Gestionnaire de modules externes. Les fichiers de profil ne changent pas.
