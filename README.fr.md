[English](README.md) | **Français**

# HNCS : profil couleur Hasselblad X2D II pour Lightroom Classic

Un profil caméra Adobe (`.dcp`) gratuit pour Lightroom Classic et Camera Raw qui reproduit la couleur HNCS de Hasselblad du X2D II 100C : un 3FR prend le rendu de Phocus sans ouvrir Phocus. C'est un profil caméra, pas un plug-in ni un preset, et il fonctionne sur Mac et Windows.

<p align="center"><img src="docs/figures/hero.png" width="900" alt="HNCS for Lightroom : trois photos du X2D II, Phocus sur la moitié gauche et Camera Raw avec HNCS sur la moitié droite"></p>

<p align="center"><img src="docs/figures/comparison.png" width="900" alt="Cinq photos du X2D II en quatre colonnes : Phocus (HNCS), le JPEG du boîtier, Lightroom / Camera Raw avec HNCS, et Camera Raw avec Adobe Standard"></p>

*Cinq photos tenues à part de l'ajustement. Camera Raw à l'exposition 0, sans aucun réglage, corrections d'objectif désactivées ; la luminosité de chaque photo est celle que le boîtier écrit dans le 3FR. Phocus et le JPEG du boîtier servent de références. Les légendes des images sont en anglais.*

## Télécharger

### ➜ [**HNCS-Hasselblad-X2D-II.dcp** (dernière release)](https://github.com/ThomasHMD/hncs-lightroom-profile/releases/latest/download/HNCS-Hasselblad-X2D-II.dcp)

28 Ko, pour le X2D II 100C. Toutes les versions sont dans les [Releases](https://github.com/ThomasHMD/hncs-lightroom-profile/releases). La source du profil et des outils qui l'ont fabriqué, c'est ce dépôt, sous licence MIT (voir [Licence](#licence)).

## Nouveautés

<p align="center"><img src="docs/figures/versions.png" width="900" alt="Un coucher de soleil simulé passé dans la table de couleurs de HNCS 1.0, 1.1 et 1.2 : l'arc sombre s'efface en 1.1, l'anneau autour du soleil disparaît en 1.2"></p>

### 1.2 : plus d'anneau autour du soleil

Dans les couchers de soleil à contre-jour, la version 1.1 pouvait dessiner un anneau orange plus sombre autour du soleil. La cause était le haut de la table de couleurs 3D : pour les tons jaune-orangé très clairs, elle divisait la luminosité par deux, si bien que le ciel s'assombrissait en approchant du soleil, puis passait d'un coup au blanc. Dans la 1.2, la luminosité monte toujours avec la lumière, partout dans la table. Rien d'autre ne change : la fidélité à Phocus est identique, et la correction des bandes de la 1.1 est gardée. Le contrôle automatique refuse désormais aussi un profil dont la luminosité redescend quelque part.

### 1.1 : correction des bandes dans les ciels

La version 1.0 pouvait montrer de légères bandes roses et vertes dans les dégradés lisses et pâles, typiquement un ciel de coucher de soleil qui passe du bleu au jaune près de l'horizon (merci à l'utilisateur de X2D qui l'a signalé avec un fichier de test). La cause était la table de couleurs 3D du profil : pour les couleurs presque grises, sa correction changeait brutalement d'une teinte à la voisine. Un ciel pâle qui passe du bleu au jaune traverse le gris : il balaie toutes les teintes en quelques pixels, et chacune recevait une correction un peu différente.

La 1.1 lisse cette partie de la table et réduit de moitié la correction des couleurs presque grises. Le reste (courbe de tons, matrices, couleurs saturées) ne change pas. Sur la photo signalée, les bandes ont disparu et le ciel est à peu près aussi lisse qu'avec Adobe Standard. La fidélité à Phocus ne s'est pas dégradée : sur 16 des 41 photos de test, rendues à nouveau dans Camera Raw, le ΔE2000 médian vaut 1,03 pour la 1.1 et 1,05 pour la 1.0 avec l'exposition réglée photo par photo, et 1,21 contre 1,30 tel quel. Un contrôle permanent fait maintenant passer des dégradés synthétiques par le gris, dans `tools/adoucir_look.py --self-test`.

Si vous avez installé une version précédente, remplacez le fichier par le nouveau (même nom, même endroit) et relancez Lightroom. Le profil garde son nom, **HNCS** : les photos qui l'utilisent déjà passent d'elles-mêmes à la nouvelle version.

## Installer

Le profil va dans le dossier **utilisateur** de Camera Raw. Pas dans le dossier de l'application, pas dans le dossier système.

1. Quittez Lightroom Classic.
2. Copiez `HNCS-Hasselblad-X2D-II.dcp` dans :
   - **macOS** : `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles/`
     (dans le Finder : Aller ▸ Aller au dossier…, puis collez le chemin ; le dossier `Library` est masqué)
   - **Windows** : `%APPDATA%\Adobe\CameraRaw\CameraProfiles\`
     (collez-le dans la barre d'adresse de l'Explorateur ; c'est `C:\Users\<votre-nom>\AppData\Roaming\Adobe\CameraRaw\CameraProfiles\`)
3. Relancez Lightroom Classic.

Pourquoi ce dossier : les dossiers système (`/Library/Application Support/Adobe/CameraRaw/CameraProfiles/` sur macOS, `C:\ProgramData\Adobe\CameraRaw\CameraProfiles\` sur Windows) contiennent les profils d'Adobe et sont gérés par son installateur et ses mises à jour, qui peuvent les réécrire. Le dossier utilisateur est le vôtre : Lightroom le lit, et une mise à jour n'y touche pas. Après une grosse mise à jour de Lightroom ou de Camera Raw, vérifiez que le profil est toujours listé. Sinon, le fichier est toujours dans le dossier : relancez d'abord Lightroom, et certains utilisateurs disent que réinitialiser ses préférences ramène les profils tiers.

Copier le fichier à la main, comme ci-dessus, est la méthode que j'ai testée.

## L'utiliser

1. Ouvrez un 3FR du X2D II dans le module Développement.
2. Panneau Réglages de base ▸ **Profil** ▸ Parcourir (l'icône à quatre carrés). Le profil s'appelle **HNCS** et se trouve dans le groupe **Profils**, sous Camera Matching (pas dans Adobe Raw). Le curseur **Niveau** en haut de l'explorateur permet de l'atténuer. Cliquez sur l'étoile pour le mettre en favori : il apparaît alors dans la liste déroulante Profil.
3. Le profil n'apparaît que pour les fichiers du X2D II. Il est associé au nom d'appareil d'Adobe, `Hasselblad 100-22-Coated6`. Un autre boîtier Hasselblad de 100 mégapixels peut porter le même nom, mais je n'ai testé que le X2D II 100C.

### En faire le défaut du X2D II

1. Sur une photo du X2D II, choisissez HNCS comme ci-dessus.
2. Dans le panneau Paramètres prédéfinis, clic droit ou menu **+** ▸ **Créer un paramètre prédéfini…**. Nommez-le `HNCS`, cliquez sur **Ne rien sélectionner**, cochez seulement **Traitement et profil**, créez.
3. Lightroom Classic ▸ Préférences (Édition ▸ Préférences sous Windows) ▸ onglet **Paramètres prédéfinis** ▸ **Paramètres par défaut Raw**. Cochez **Remplacer le paramètre global pour des appareils photo spécifiques**, choisissez **Hasselblad X2D II 100C** dans la liste **Appareil photo :**, puis dans **Par défaut :** choisissez **Paramètres prédéfinis** et votre paramètre `HNCS`.

La liste des appareils vient des photos raw déjà présentes dans votre catalogue : importez d'abord au moins une photo du X2D II. Ne choisissez pas **Paramètres de l'appareil photo** pour cela : il ne reprend que les styles appliqués dans le boîtier et ne connaît pas ce profil. Le défaut s'applique aux photos importées ensuite ; pour celles déjà dans le catalogue, appliquez-leur le paramètre prédéfini. Les noms de menus sont ceux de l'application Lightroom Classic elle-même ; documentation d'Adobe (en anglais) : [Set up default settings for raw images](https://helpx.adobe.com/lightroom-classic/desktop/help/raw-defaults.html).

## Luminosité

HNCS règle aussi la luminosité de chaque photo automatiquement. Le boîtier écrit cette décision dans le 3FR (la balise `BaselineExposure` : 0, +1 ou +2 IL selon la prise de vue), et Lightroom et Camera Raw l'appliquent déjà d'eux-mêmes. La luminosité suit donc celle de Phocus, à peu près. Sur les 41 images que j'ai gardées de côté pour le test, l'écart restant avec Phocus est faible, en général dans ±0,2 IL (médiane −0,03 IL, extrêmes −0,57 et +0,20 IL). Les photos dont la balise vaut +1 ou +2 IL sortent environ 0,2 IL plus claires que Phocus. Une petite retouche du curseur Exposition est donc possible, et parfois utile.

## Précision

Les écarts sont mesurés contre un export Phocus (réglages par défaut, SDR) du même 3FR, en ΔE2000 (environ 1 : à peine visible ; 2 à 3 : visible côte à côte). Pour l'échelle, Phocus et le JPEG du boîtier diffèrent entre eux d'environ 2 (médiane). Les mesures utilisent de vrais rendus Camera Raw (voir [Comment il a été fait](#comment-il-a-été-fait)), sur **41 photos tenues à part de l'ajustement**, de 3 objectifs (XCD 35-100E, 38V, 55V), au centre du cadre, sur des zones uniformes.

| ΔE2000 médiane / 90e centile | HNCS | Adobe Standard |
|---|---|---|
| Les 41 photos, Camera Raw tel quel (exposition 0) | **1,56** / 4,45 | 2,51 / 5,58 |
| Les 41, avec l'exposition réglée photo par photo | **1,23** / 3,24 | 1,87 / 4,18 |
| Lumière chaude sous 4500 K (10 photos), tel quel | **1,56** / 4,75 | 3,22 / 5,83 |
| ISO 3200 et plus (4 photos), tel quel | **3,67** / 5,47 | 4,48 / 6,29 |
| Zones claires (24 photos), tel quel | **2,35** / 6,37 | 2,88 / 6,80 |

Le tableau ci-dessus et les figures ont été faits avec la version 1.0 ; la 1.1 et la 1.2 ne diffèrent que dans les couleurs pâles, presque grises, et dans les tons chauds très clairs (voir [Nouveautés](#nouveautés)).

Les limites, telles qu'elles sont :

- Les **hauts ISO** (3200 et plus) et les **hautes lumières** sont les points faibles : l'écart avec Phocus y reste grand. Seules 4 photos à ISO 3200 et plus ont été gardées de côté, ce chiffre n'est donc pas solide.
- Phocus rend les gris neutres légèrement chauds. Un profil caméra ne peut pas porter cela sans perturber la balance des blancs : HNCS garde donc les neutres neutres. Si vous aimez la chaleur de Phocus, réchauffez un peu la balance des blancs.
- Phocus corrige aussi la distorsion et le vignetage de l'objectif. Ce profil ne le fait pas ; les mesures ont été faites avec les corrections d'objectif de Camera Raw désactivées.
- Le rendu **HDR** de Phocus n'est pas couvert.
- Les ciels chauds des couchers de soleil sortent un peu moins saturés et plus clairs près du soleil que dans Phocus ou le HEIC du boîtier. Phocus garde ces jaunes ; c'est le traitement des hautes lumières propre à Camera Raw qui en perd une partie, avec tous les profils (Adobe Standard et Adobe Color en perdent davantage), et pas autant d'une photo à l'autre : un profil fixe ne peut pas le compenser. Baissez les Hautes lumières et ajoutez un peu de Vibrance pour vous en rapprocher.
- Les dégradés lisses d'orange vif peuvent encore montrer par endroits de légères bandes : la table de couleurs reste irrégulière aux saturations moyennes. Pas encore vu sur une vraie photo.
- Trois objectifs ont été testés. Les autres (XCD 90V, 25V, 20…) ne le sont pas, et Phocus éclaircit différemment selon l'objectif.
- Les mesures ont été faites sur un seul boîtier et par échantillonnage de zones uniformes. Les tons chair et les textures fines n'ont pas été mesurés à part.
- Elles ont été faites avec Camera Raw piloté depuis Photoshop, c'est-à-dire le moteur que Lightroom utilise, pas avec Lightroom Classic lui-même.

Les outils écrivent eux-mêmes ces rapports : on peut les régénérer avec ses propres fichiers (voir [`tools/README.md`](tools/README.md)).

## Comment il a été fait

J'ai exporté des paires de fichiers : le 3FR, et la même photo depuis Phocus avec ses réglages HNCS par défaut. À partir d'environ 170 photos (trois objectifs, ISO 50 à 25600, lumière du jour et lumière chaude), j'ai ajusté le profil dans la chaîne de rendu d'Adobe elle-même (spécification DNG 1.7) : une courbe de tons, une petite correction de la matrice couleur et une table de couleurs 3D (teinte, saturation, valeur), neutres intacts. Puis je l'ai corrigé en deux tours d'après de **vrais rendus Camera Raw**, parce que mon modèle de la chaîne s'écartait de Camera Raw d'environ 1,6 ΔE, surtout dans les hautes lumières. Une photo sur quatre, choisie par objectif, n'a jamais servi à l'ajustement ; le tableau ci-dessus porte sur celles-là. (12 de ces 41 ont aussi servi à choisir entre les tours de correction, un petit biais ; l'écart entre les deux derniers tours était négligeable.)

Les outils sont dans [`tools/`](tools/) (Python, commentaires en français), avec un [README](tools/README.md) qui dit ce que fait chaque script et ce qu'il demande. Les mesures sur lesquelles le profil a été ajusté sont publiées dans [`data/`](data/README.md) (CC BY 4.0) : les scripts d'ajustement tournent donc depuis ce dépôt.

Je l'ai fait avec l'aide de Claude Code (l'assistant de programmation d'Anthropic), qui a écrit une bonne part du Python de `tools/` sous ma direction. La méthode, les choix et les mesures sont les miens, et j'ai vérifié les résultats sur de vrais rendus Camera Raw.

## Crédits et travaux antérieurs

- [Konrad Michels, « What a Lightroom Camera Profile Can and Cannot Reproduce from Phocus »](https://blog.tonalphoto.com/lightroom-camera-profile-phocus-color/) (Tech Behind the Frame) : même approche, un profil caméra Lightroom ajusté sur des rendus Phocus du X2D II. Son profil n'est pas distribué, c'est pourquoi j'ai rendu public le mien.
- [dcamprof](https://github.com/Entropy512/dcamprof) (miroir GitHub) d'Anders Torger, utilisé pour recouper mon modèle de rendu et comme première approche. Il est sous GPL-3.0 et n'est pas inclus : mes scripts ne font que l'appeler comme programme externe. J'ai gardé mon propre ajustement, qui mesurait mieux dans Camera Raw.
- La structure du profil suit la spécification DNG d'Adobe. Les matrices couleur viennent du profil d'Adobe (voir [Licence](#licence)).

## Licence

- **Les outils et la documentation** : MIT ([`LICENSE`](LICENSE)).
- **Le profil** (la courbe de tons, la table de couleurs 3D et la correction que j'ai appliquée aux matrices forward d'Adobe) : MIT aussi. Les deux matrices couleur (`ColorMatrix1`, `ColorMatrix2`) et les illuminants de calibration stockés dans le fichier sont copiés tels quels du profil `Adobe Standard` du même appareil, qu'Adobe distribue avec Lightroom (le profil porte la mention « Allow Copying »). Je ne revendique aucun droit dessus. Détails : [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- **Les données** (`data/`, les mesures par blocs) : CC BY 4.0, © Thomas Hammoudi. Citez-moi et renvoyez à ce dépôt. Détails dans [`data/README.md`](data/README.md) (en anglais).
- **Les photos** (les deux figures de `docs/figures/`) : © Thomas Hammoudi, tous droits réservés. Elles ne sont pas sous les licences ci-dessus, qui couvrent le code, le profil, les données et les analyses.

## Avertissement

Projet indépendant, **non affilié à Hasselblad ni à Adobe, et non approuvé par eux**. « Hasselblad », « X2D », « Phocus » et « HNCS » (Hasselblad Natural Colour Solution) sont des marques de leurs propriétaires, comme « Adobe », « Lightroom » et « Camera Raw ». Ce dépôt ne contient aucun logiciel Hasselblad ni aucun fichier image de Phocus : seulement un profil caméra qui approche un rendu, et des moyennes par blocs (16 x 16 px, zones uniformes) mesurées sur des exports Phocus de mes propres photos. À utiliser à vos risques.
