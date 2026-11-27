# v2.2.0: truer oranges and reds in the profile, better brightness in the Lightroom module / oranges et rouges plus justes dans le profil, meilleure luminosité dans le module Lightroom

*🇫🇷 Version française plus bas.*

**The profile goes to 2.2** (same file names, same profile name HNCS: photos already set to it switch by themselves) and the optional **Lightroom Classic module** goes to **1.2.0**.

## What changed

### Profile 2.2

- **Saturated oranges and reds are closer to Phocus.** Version 2.0 rendered them a little dull and slightly off in hue. I corrected only the orange-red sector of the 3D color table (hue and saturation). Brightness, blues, skies, grays, the tone curve and the matrices are exactly as in 2.0. The X2D 100C variant got the same table.
- Camera Raw against Phocus 4.2.3, on 45 new photos (37 very orange, 8 skies), 2.2 against 2.0 with the same module: closer on 17, the same on 28, **farther on none** with lens corrections on (18 / 27 / 0 off); median ΔE2000 0.97 to 0.77 (0.80 to 0.69 off). Orange areas alone (33 photos): closer on 31, farther on 2. Blue areas identical, no sky farther. My banding tests (strong changes under a sky mask) give the same result as 2.0.
- For reference, against [Rockfish X2D II](https://blog.tonalphoto.com/rockfish-x2d-ii/) used as a user would (Exposure 0, no module), on the same 45 photos: HNCS closer to Phocus on 35, the same on 1, farther on 9 (35 / 5 / 5 with lens corrections off). On orange areas alone, closer on 29 and farther on 4 (25 and 6 off).
- Limits: my photos only, one body, Phocus 4.2.3 as the reference. A very saturated red in warm light (about 3,000 K) came out slightly farther in my cross-check (about 0.2 ΔE, a calculation, not seen in real renders). The scripts in `tools/` are still those of versions 1.x.

### Lightroom module 1.2.0

- **Better brightness on photos where the camera made brightness decisions** (a JPEG or an HDR HEIF recorded with the RAW). The module lowers their Exposure a bit more (−0.05 instead of +0.05 for the "lift about 0 EV" case) and, with lens corrections on, adds a small correction per lens (XCD 55V −0.15, 35-100E −0.04, 38V −0.13). With lens corrections off, or an unknown lens, nothing is added. The 38V value comes from the other two lenses: no 38V photo with camera decisions was available to measure it.
- **The XCD 55V is closer to Phocus with lens corrections off**: Exposure −0.08 instead of −0.05 for photos without camera decisions below ISO 6400.
- **No regression against 1.1.0**, judged on 71 control photos in Camera Raw against Phocus 4.2.3. All other photos come out exactly as with 1.1.0.
- Checked outside Lightroom (rule against a Python reference on 57,000 cases); not tried in Lightroom Classic yet.

## Update

Download the `.dcp` for your camera again, replace the old one in the same folder and restart Lightroom. For the module, download `HNCS-Lightroom-module.zip`, replace the `reglages-x2d.lrplugin` folder you use, and reload the module in File ▸ Plug-in Manager. The 2.0 / 2.1 profile stays available in the v2.1.0 release.

SHA-256:
- `HNCS-Hasselblad-X2D-II.dcp`: `1d5899f21ca304433c835667801ab7ef266ed2303b3470e142556ba32b309e1e`
- `HNCS-Hasselblad-X2D-100C.dcp`: `5347be4853e22ffa419b1633cc81ac7cb38f62902eba3cfe0cda1cfff72cc80a`
- `HNCS-Lightroom-module.zip`: `663202ff2b15111a451b9a9ab354bb4811441fbe095786b0579f609527542b46`

---

## 🇫🇷 En français

**Le profil passe en 2.2** (mêmes noms de fichier, même nom de profil HNCS : les photos qui l'utilisent passent seules à la nouvelle version) et le **module Lightroom Classic** facultatif passe en **1.2.0**.

## Ce qui change

### Profil 2.2

- **Les oranges et les rouges saturés sont plus proches de Phocus.** La version 2.0 les rendait un peu ternes et légèrement décalés en teinte. J'ai corrigé seulement le secteur orange-rouge de la table de couleurs 3D (teinte et saturation). La luminosité, les bleus, les ciels, les gris, la courbe de tons et les matrices sont exactement ceux de la 2.0. La variante X2D 100C a reçu la même table.
- Camera Raw contre Phocus 4.2.3, sur 45 photos nouvelles (37 très orangées, 8 ciels), 2.2 contre 2.0 avec le même module : plus proche sur 17, égal sur 28, **plus éloigné sur aucune** avec les corrections d'objectif actives (18 / 27 / 0 coupées) ; ΔE2000 médian de 0,97 à 0,77 (0,80 à 0,69 coupées). Zones orangées seules (33 photos) : plus proche sur 31, plus éloigné sur 2. Zones bleues identiques, aucun ciel plus éloigné. Mes tests de bandes (forts changements sous un masque de ciel) donnent le même résultat que la 2.0.
- À titre de repère, contre [Rockfish X2D II](https://blog.tonalphoto.com/rockfish-x2d-ii/) tel qu'un utilisateur s'en sert (Exposition 0, sans module), sur les mêmes 45 photos : HNCS plus proche de Phocus sur 35, égal sur 1, plus éloigné sur 9 (35 / 5 / 5 corrections coupées). Sur les seules zones orangées, plus proche sur 29 et plus éloigné sur 4 (25 et 6 coupées).
- Limites : mes photos seulement, un seul boîtier, Phocus 4.2.3 pour référence. Un rouge très saturé en lumière chaude (environ 3 000 K) sort un peu plus éloigné dans ma validation croisée (environ 0,2 de ΔE, un calcul, pas vu dans les vrais rendus). Les scripts de `tools/` sont toujours ceux des versions 1.x.

### Module Lightroom 1.2.0

- **Meilleure luminosité sur les photos où le boîtier a pris des décisions de luminosité** (un JPEG ou un HEIF HDR enregistré avec le RAW). Le module baisse un peu plus leur Exposition (−0,05 au lieu de +0,05 pour le cas « remontée d'environ 0 IL ») et, avec les corrections d'objectif actives, ajoute une petite correction par objectif (XCD 55V −0,15, 35-100E −0,04, 38V −0,13). Corrections coupées, ou objectif inconnu : rien n'est ajouté. La valeur du 38V vient des deux autres objectifs : aucune photo de 38V avec décisions du boîtier n'était disponible pour la mesurer.
- **Le XCD 55V est plus juste avec les corrections d'objectif coupées** : Exposition −0,08 au lieu de −0,05 pour les photos sans décisions du boîtier sous ISO 6400.
- **Pas de régression contre la 1.1.0**, jugé sur 71 photos de contrôle dans Camera Raw contre Phocus 4.2.3. Toutes les autres photos sortent exactement comme avec la 1.1.0.
- Vérifié hors de Lightroom (la règle contre une référence Python sur 57 000 cas) ; pas encore essayé dans Lightroom Classic.

## Mise à jour

Téléchargez de nouveau le `.dcp` de votre boîtier, remplacez l'ancien dans le même dossier et relancez Lightroom. Pour le module, téléchargez `HNCS-Lightroom-module.zip`, remplacez le dossier `reglages-x2d.lrplugin` que vous utilisez, et rechargez le module dans Fichier ▸ Gestionnaire de modules externes. Le profil 2.0 / 2.1 reste disponible dans la release v2.1.0.
