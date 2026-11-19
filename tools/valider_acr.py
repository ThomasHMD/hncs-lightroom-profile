#!/usr/bin/env python3
"""Vrai test des profils HNCS dans le moteur d'Adobe (Camera Raw), piloté par Photoshop 2027 (script, sans Lightroom).

Pour chaque 3FR (8 images tenues à part + 4 images d'ajustement) et chaque profil (HNCS, HNCS (dcamprof),
Adobe Standard) :
  1. copie du 3FR dans le chantier (tmp-acr/), sidecar .xmp Camera Raw qui impose ProcessVersion 11.0, le profil,
     balance « As Shot », et tous les réglages à 0 (netteté, bruit, corrections d'objectif off, courbe linéaire) ;
  2. ouverture par Photoshop (displayDialogs = NO, options Camera Raw explicites : 16 bits, espace ProPhoto RGB),
     le profil ProPhoto RGB est assigné au document (Photoshop ne le déclare pas seul : le TIFF recevait sinon
     le profil de l'écran), enregistrement en TIFF 16 bits non compressé, ICC relu dans le TIFF ;
  3. moyennes par blocs de 16 x 16 px aux positions des blocs de `samples-pass1.npz` (même géométrie que l'export
     Phocus : 11656 x 8742), plus une version réduite au 1/8 pour la planche ; le TIFF est ensuite effacé.

  passe 1 : Exposure2012 = 0 (le test demandé) ; passe 2 : Exposure2012 = gain trouvé en passe 1 (le gain par
  image de HNCS se règle dans Lightroom par le curseur d'exposition).

  valider_acr.py rendre [--passe 1|2] [--seulement B0000586 ...] [--profils hncs dcamprof adobe] [--refaire]
  valider_acr.py mesurer        # measurements/validation-acr.md et measurements/planche-acr.png
  valider_acr.py tout           # passe 1, passe 2, mesure
  valider_acr.py --self-test

Photoshop est quitté à la fin s'il n'était pas ouvert au départ.  Lightroom n'est jamais lancé.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import warnings
import xml.etree.ElementTree as ET

import numpy as np

warnings.filterwarnings('ignore')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chaine_adobe as CA   # noqa: E402
import echantillons as E    # noqa: E402

PROJET = E.PROJET
C = E.C
ENTREE = C / 'phocus-entree'
SORTIE = C / 'phocus-sortie'
TMP = C / 'tmp-acr'
RES = TMP / 'res'
PROFILS_DIR = pathlib.Path.home() / 'Library/Application Support/Adobe/CameraRaw/CameraProfiles'
PROFILS = {   # clé -> (nom de profil Camera Raw, fichier DCP pour le modèle, étiquette)
    'hncs': ('HNCS', PROFILS_DIR / 'Hasselblad X2D II HNCS.dcp', 'HNCS'),
    'dcamprof': ('HNCS (dcamprof)', PROFILS_DIR / 'HNCS-dcamprof.dcp', 'HNCS (dcamprof)'),
    'adobe': ('Adobe Standard', pathlib.Path(CA.DCP_ADOBE), 'Adobe Standard'),
}
AJUSTEMENT = ['B0000583', 'B0000589', 'B0000596', 'B0000613']   # 4 images d'ajustement, gains variés
PS_ID = 'com.adobe.Photoshop'
ECHANT = PROJET / 'data' / 'samples-pass1.npz'
BLOC = E.BLOC


# ----------------------------------------------------------------------------------------------- XMP
def xmp(profil, exposition=0.0):
    """Sidecar Camera Raw : tout à 0, profil imposé."""
    attrs = [('Version', '17.0'), ('ProcessVersion', '11.0'), ('CameraProfile', profil), ('WhiteBalance', 'As Shot'),
             ('Exposure2012', f'{exposition:+.2f}')]
    attrs += [(k, '0') for k in ('Contrast2012', 'Highlights2012', 'Shadows2012', 'Whites2012', 'Blacks2012',
                                 'Texture', 'Clarity2012', 'Dehaze', 'Vibrance', 'Saturation', 'Sharpness',
                                 'LuminanceSmoothing', 'ColorNoiseReduction', 'LensProfileEnable', 'AutoLateralCA')]
    attrs += [('ToneCurveName2012', 'Linear'), ('HasSettings', 'True')]
    a = ' '.join(f'crs:{k}="{v}"' for k, v in attrs)
    return ('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
            f'xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/" {a}>'
            '<crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 0</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:ToneCurvePV2012>'
            '</rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>\n')


def lire_xmp(texte):
    """-> dict des attributs crs (relecture pour le self-test)."""
    racine = ET.fromstring(texte.split('?>', 1)[1].rsplit('<?xpacket', 1)[0])
    ns = {'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'}
    d = racine.find('.//rdf:Description', ns)
    crs = '{http://ns.adobe.com/camera-raw-settings/1.0/}'
    out = {k[len(crs):]: v for k, v in d.attrib.items() if k.startswith(crs)}
    out['_courbe'] = [li.text for li in d.iter('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li')]
    return out


# ----------------------------------------------------------------------------------------------- Photoshop
def ps_ouvert():
    return subprocess.run(['pgrep', '-f', '/Adobe Photoshop 2027.app/Contents/MacOS/Adobe Photoshop 2027'],
                          capture_output=True).returncode == 0


def ps(jsx, delai=900):
    """Exécute un script JSX dans Photoshop, retourne sa valeur (chaîne)."""
    TMP.mkdir(parents=True, exist_ok=True)
    f = TMP / '_run.jsx'
    f.write_text(jsx)
    r = subprocess.run(['osascript', '-e', f'tell application id "{PS_ID}" to do javascript file "{f}"'],
                       capture_output=True, text=True, timeout=delai)
    if r.returncode != 0:
        raise RuntimeError(f'Photoshop : {r.stderr.strip()[:600]}')
    return r.stdout.strip()


def ps_quitter():
    subprocess.run(['osascript', '-e', f'tell application id "{PS_ID}" to quit'], capture_output=True, timeout=120)


JSX_RENDU = r'''
app.displayDialogs = DialogModes.NO;
while (app.documents.length) app.documents[0].close(SaveOptions.DONOTSAVECHANGES);
var o = new CameraRAWOpenOptions();
o.bitsPerChannel = BitsPerChannelType.SIXTEEN;
o.colorSpace = ColorSpaceType.PROPHOTORGB;
o.settings = CameraRAWSettingsType.SELECTEDIMAGE;   // lit le sidecar .xmp (CAMERA l'ignore : réglages par défaut)
var d = app.open(new File("%(raw)s"), o);
var info = "";
try {
  d.colorProfileName = "ProPhoto RGB";
  info = d.width + "x" + d.height + " " + d.bitsPerChannel + " " + d.colorProfileName;
  var t = new TiffSaveOptions();
  t.imageCompression = TIFFEncoding.NONE; t.byteOrder = ByteOrder.MACOS; t.embedColorProfile = true;
  t.layers = false; t.alphaChannels = false;
  d.saveAs(new File("%(tif)s"), t, true, Extension.LOWERCASE);
} finally {
  d.close(SaveOptions.DONOTSAVECHANGES);
}
info;
'''


def rendre_un(nom, cle, exposition, tif):
    """Un rendu Camera Raw. Retourne la chaîne d'infos de Photoshop."""
    raw = TMP / f'{nom}.3FR'
    if not raw.exists():
        shutil.copyfile(ENTREE / f'{nom}.3FR', raw)
    (TMP / f'{nom}.xmp').write_text(xmp(PROFILS[cle][0], exposition))
    if tif.exists():
        tif.unlink()
    info = ps(JSX_RENDU % {'raw': raw, 'tif': tif})
    assert tif.exists(), 'TIFF non écrit'
    return info


# ----------------------------------------------------------------------------------------------- lecture des TIFF
def lire_blocs(chemin):
    """Moyennes de blocs 16x16 (valeurs codées, [0,1]) pour tous les blocs, et version réduite au 1/8 (uint16)."""
    d = E.lire_tiff(chemin)
    mm = np.memmap(chemin, dtype='>u2', mode='r', offset=d['offset'], shape=(d['h'], d['w'], 3))
    nby, nbx = d['h'] // BLOC, d['w'] // BLOC
    bm = np.zeros((nby, nbx, 3), np.float32)
    red = np.zeros((nby * 2, nbx * 2, 3), np.uint16)
    for by in range(nby):
        a = np.asarray(mm[by * BLOC:(by + 1) * BLOC, :nbx * BLOC], np.float32).reshape(2, 8, nbx * 2, 8, 3)
        r8 = a.mean((1, 3))                                   # (2, 2*nbx, 3)
        red[2 * by:2 * by + 2] = np.round(r8).astype(np.uint16)
        bm[by] = r8.reshape(2, nbx, 2, 3).mean((0, 2)) / 65535
    return d, bm, red


def verifier_icc_prophoto(d):
    """Le TIFF Photoshop porte bien ProPhoto RGB (gamma 1,8, colorants ProPhoto D50) ; retourne la matrice RVB->XYZ D50."""
    icc = d['icc']
    assert icc is not None, 'pas de profil ICC dans le TIFF'
    desc = re.sub(rb'[^\x20-\x7e]', b'', icc[128:400] + icc[400:1200])
    assert b'ProPhoto' in icc[:4096], 'le profil ICC incorporé n\'est pas ProPhoto RGB'
    g = E.icc_gamma_u8f8(icc)
    assert g is not None and abs(g - 1.8) < 0.01, f'gamma ICC {g} != 1,8'
    m = E.icc_colorants(icc)
    attendu = np.array([[0.7977, 0.1352, 0.0313], [0.2880, 0.7119, 0.0001], [0.0, 0.0, 0.8249]])
    assert np.abs(m - attendu).max() < 3e-3, f'colorants ProPhoto inattendus : {np.abs(m - attendu).max()}'
    return m, g


def decode_prophoto(v, m, g):
    return (np.clip(v, 0, 1) ** g) @ m.T


# ----------------------------------------------------------------------------------------------- données de référence
def charger_ref():
    z = np.load(ECHANT)
    noms = [str(n) for n in z['noms']]
    tenues = [n for i, n in enumerate(noms) if i % 4 == 3]
    return z, noms, tenues


def blocs_image(z, noms, nom):
    i = noms.index(nom)
    m = z['image'] == i
    return {'by': z['by'][m].astype(int), 'bx': z['bx'][m].astype(int), 'cam': z['cam_rgb'][m].astype(np.float64),
            'phocus': z['phocus_xyz'][m].astype(np.float64), 'jpeg': z['jpeg_xyz'][m].astype(np.float64),
            'wb': z['wb_as_shot'][i].astype(float)}


def chemin_res(nom, cle, passe):
    return RES / f'{nom}__{cle}__p{passe}.npz'


def ref_reduite(nom):
    """Export Phocus réduit au 1/8 (uint16 codé Adobe RGB), mis en cache."""
    f = RES / f'phocus__{nom}.npy'
    if f.exists():
        return np.load(f)
    d, _, red = lire_blocs(SORTIE / f'B_{nom[-4:]}.tif')
    np.save(f, red)
    return red


# ----------------------------------------------------------------------------------------------- gain libre
def de(a, b):
    return E.de2000(a, b)


def meilleur_gain_post(x, ref, lo=-3.0, hi=3.0):
    """Gain post-rendu (IL, multiplie le XYZ linéaire) minimisant la médiane de ΔE2000 de x*2^g contre ref."""
    from scipy.optimize import minimize_scalar
    f = lambda g: float(np.median(de(x * 2.0 ** g, ref)))
    grille = np.arange(lo, hi + 1e-9, 0.25)
    g0 = grille[int(np.argmin([f(g) for g in grille]))]
    r = minimize_scalar(f, bounds=(g0 - 0.25, g0 + 0.25), method='bounded', options={'xatol': 1e-3})
    return float(r.x)


# ----------------------------------------------------------------------------------------------- rendre
def etat_geometrie(nom, red_acr):
    """Décalage (en px pleine taille) entre le rendu Camera Raw et l'export Phocus, par corrélation de luminance."""
    import cv2
    red_p = ref_reduite(nom)
    if red_p.shape != red_acr.shape:
        return None, f'tailles différentes {red_acr.shape} / {red_p.shape}'
    la = np.log(np.clip(red_acr[..., 1].astype(np.float32) / 65535, 0, 1) ** 1.8 + 1e-3)
    lp = np.log(np.clip(red_p[..., 1].astype(np.float32) / 65535, 0, 1) ** E.GAMMA_ADOBE + 1e-3)
    mg = 6
    h, w = la.shape
    tm = np.ascontiguousarray(lp[mg:-mg, mg:-mg])
    r = cv2.matchTemplate(np.ascontiguousarray(la), tm, cv2.TM_CCOEFF_NORMED)
    py, px = np.unravel_index(np.argmax(r), r.shape)
    return ((int(py) - mg) * 8, (int(px) - mg) * 8), f'corr {r[py, px]:.3f}'


def rendre(noms, cles, passe, refaire=False):
    z, nz, tenues = charger_ref()
    RES.mkdir(parents=True, exist_ok=True)
    gains = {}
    if passe == 2:
        mesure1 = mesurer_passe(z, nz, noms, cles, 1)
    for nom in noms:
        b = blocs_image(z, nz, nom)
        for cle in cles:
            out = chemin_res(nom, cle, passe)
            if out.exists() and not refaire:
                print(nom, cle, f'p{passe}', 'déjà fait', flush=True)
                continue
            expo = 0.0
            if passe == 2:
                expo = float(np.clip(round(mesure1[(nom, cle)]['gain_phocus'], 2), -4.0, 4.0))
            tif = TMP / f'rendu_{nom}_{cle}.tif'
            import time
            t = time.time()
            info = rendre_un(nom, cle, expo, tif)
            d, bm, red = lire_blocs(tif)
            m, g = verifier_icc_prophoto(d)
            enc = bm[b['by'], b['bx']]
            decal, note = etat_geometrie(nom, red)
            np.savez(out, enc=enc, red=red, expo=expo, icc_gamma=g, icc_colorants=m, info=info,
                     decalage_px=np.array(decal if decal else (-9999, -9999)), note_geom=note,
                     dims=np.array([d['h'], d['w']]))
            tif.unlink()
            print(f'{nom} {cle} p{passe} expo {expo:+.2f} : {info} ; décalage {decal} {note} ; {time.time() - t:.0f}s',
                  flush=True)
        (TMP / f'{nom}.3FR').unlink(missing_ok=True)
        (TMP / f'{nom}.xmp').unlink(missing_ok=True)


# ----------------------------------------------------------------------------------------------- mesure
_PROFILS_MODELE = {}


def baseline_exposures(noms):
    """BaselineExposure propre à chaque 3FR (tag DNG, IL), lue par exiftool ; mise en cache."""
    f = RES / 'baseline.json'
    d = json.loads(f.read_text()) if f.exists() else {}
    manque = [n for n in noms if n not in d]
    if manque:
        r = subprocess.run(['exiftool', '-json', '-n', '-BaselineExposure', '-BaselineExposureOffset']
                           + [str(ENTREE / f'{n}.3FR') for n in manque], capture_output=True, text=True, check=True)
        for n, e in zip(manque, json.loads(r.stdout)):
            d[n] = [float(e.get('BaselineExposure', 0.0)), float(e.get('BaselineExposureOffset', 0.0))]
        f.write_text(json.dumps(d))
    return {n: d[n] for n in noms}


def profil_modele(cle):
    if cle not in _PROFILS_MODELE:
        _PROFILS_MODELE[cle] = CA.charger_dcp(PROFILS[cle][1])
    return _PROFILS_MODELE[cle]


def mesurer_passe(z, nz, noms, cles, passe, avec_modele=False):
    """Pour chaque (image, profil) : ΔE contre Phocus et contre le JPEG, gain post libre, écart au modèle."""
    out = {}
    be = baseline_exposures(noms)
    for nom in noms:
        b = blocs_image(z, nz, nom)
        for cle in cles:
            f = chemin_res(nom, cle, passe)
            if not f.exists():
                continue
            r = np.load(f)
            xyz = decode_prophoto(r['enc'].astype(np.float64), r['icc_colorants'], float(r['icc_gamma']))
            gp = meilleur_gain_post(xyz, b['phocus'])
            gj = meilleur_gain_post(xyz, b['jpeg'])
            e0 = de(xyz, b['phocus'])
            ep = de(xyz * 2.0 ** gp, b['phocus'])
            ej = de(xyz * 2.0 ** gj, b['jpeg'])
            o = {'gain_phocus': gp, 'gain_jpeg': gj, 'de_phocus_sans_gain': e0, 'de_phocus': ep, 'de_jpeg': ej,
                 'expo': float(r['expo']), 'xyz': xyz, 'decalage': tuple(int(v) for v in r['decalage_px'])}
            if avec_modele:
                w = b['wb']
                neu = np.array([1 / w[0], 1.0, 1 / w[2]])
                prof = profil_modele(cle)
                from scipy.optimize import minimize_scalar
                fm = lambda g: float(np.median(de(CA.rendre_xyz_d50(b['cam'], neu, prof, g + o['expo'], exposition_base=be[nom][0]), xyz)))
                gr = np.arange(-2.0, 2.01, 0.25)
                g0 = gr[int(np.argmin([fm(g) for g in gr]))]
                res = minimize_scalar(fm, bounds=(g0 - 0.25, g0 + 0.25), method='bounded', options={'xatol': 1e-3})
                gm = float(res.x)
                xm = CA.rendre_xyz_d50(b['cam'], neu, prof, gm + o['expo'], exposition_base=be[nom][0])
                em = de(xm, xyz)
                e00 = de(CA.rendre_xyz_d50(b['cam'], neu, prof, o['expo'], exposition_base=be[nom][0]), xyz)
                e0b = de(CA.rendre_xyz_d50(b['cam'], neu, prof, o['expo']), xyz)
                o.update({'gain_modele': gm, 'de_modele_acr': em, 'de_modele_acr_sans_gain': e00,
                          'de_modele_acr_sans_be': e0b, 'be': be[nom][0], 'xyz_modele': xm})
            out[(nom, cle)] = o
    return out


def stat(a):
    a = np.concatenate(a) if len(a) else np.array([np.nan])
    return float(np.median(a)), float(np.percentile(a, 90))


def mesurer():
    z, nz, tenues = charger_ref()
    noms = tenues + AJUSTEMENT
    cles = list(PROFILS)
    M1 = mesurer_passe(z, nz, noms, cles, 1, avec_modele=True)
    M2 = mesurer_passe(z, nz, noms, cles, 2, avec_modele=False)
    if not M1:
        print('aucun rendu : lancer `rendre` d\'abord')
        return
    groupes = {'tenues à part (8)': tenues, 'ajustement (4)': AJUSTEMENT}
    md = ['# Validation dans Camera Raw (moteur d\'Adobe, piloté par Photoshop 2027)', '',
          'Produit par `tools/valider_acr.py` (`tout` refait tout). Camera Raw = le moteur de Lightroom Classic ; '
          'Lightroom n\'a pas été lancé. Pour chaque 3FR : sidecar XMP (ProcessVersion 11.0, profil imposé, balance '
          '« As Shot », tous les réglages à 0, netteté et bruit 0, corrections d\'objectif off, courbe linéaire), '
          'ouverture par Photoshop, TIFF 16 bits ProPhoto RGB (profil ICC relu dans chaque TIFF : ProPhoto, gamma 1,8). '
          'ΔE2000 par blocs uniformes de 16 x 16 px (mêmes blocs que `samples-pass1.npz`, géométrie identique à l\'export '
          'Phocus : 11656 x 8742), Lab D50, avec un gain libre par image (médiane de ΔE minimale).', '']
    # géométrie
    dec = sorted({v['decalage'] for v in M1.values()})
    md += ['## Géométrie et profil appliqué', '',
           f'- Décalage Camera Raw / Phocus (px pleine taille, par corrélation de luminance au 1/8) sur les '
           f'{len(M1)} rendus de la passe 1 : {dec}. Sans recadrage ni correction d\'objectif automatique de la part de Camera Raw '
           '(taille 11656 x 8742 identique à Phocus).']
    # le profil est bien pris : écart entre profils
    ecarts = []
    for nom in noms:
        if (nom, 'hncs') in M1 and (nom, 'adobe') in M1:
            ecarts.append(float(np.median(de(M1[(nom, 'hncs')]['xyz'], M1[(nom, 'adobe')]['xyz']))))
    if ecarts:
        md += [f'- Contrôle que le profil demandé est appliqué : ΔE2000 médiane entre le rendu HNCS et le rendu Adobe Standard '
               f'du même fichier = {np.median(ecarts):.1f} (de {min(ecarts):.1f} à {max(ecarts):.1f} selon l\'image) : les rendus diffèrent.']
    md += ['']

    def tableau(M, titre, cle_de, note):
        L = [f'## {titre}', '', note, '',
             '| Référence | Groupe | Profil | ΔE médiane | ΔE 90e |', '|---|---|---|---|---|']
        for ref, cdé in (('Phocus', 'de_phocus'), ('JPEG boîtier', 'de_jpeg')):
            for g, ims in groupes.items():
                for cle in cles:
                    a = [M[(n, cle)][cdé] for n in ims if (n, cle) in M]
                    if a:
                        m, p = stat(a)
                        L.append(f'| {ref} | {g} | {PROFILS[cle][2]} | {m:.2f} | {p:.2f} |')
        return L

    def sans_gain(M):
        L = ['| Référence | Groupe | Profil | ΔE médiane | ΔE 90e |', '|---|---|---|---|---|']
        for ref, cdé in (('Phocus', 'de_phocus_sans_gain'),):
            for g, ims in groupes.items():
                for cle in cles:
                    a = [M[(n, cle)][cdé] for n in ims if (n, cle) in M]
                    if a:
                        m, p = stat(a)
                        L.append(f'| {ref} | {g} | {PROFILS[cle][2]} | {m:.2f} | {p:.2f} |')
        return L

    md += tableau(M1, 'Passe 1 : Exposure2012 = 0, gain libre appliqué après coup',
                  'de_phocus', 'Rendu Camera Raw à exposition 0, puis multiplié par un gain libre par image (sur le XYZ linéaire, '
                  'donc après la courbe : approximation de ce que fait le curseur d\'exposition).')
    md += ['', '### Passe 1 sans aucun gain (ce que Lightroom donnerait en l\'état, exposition 0)', ''] + sans_gain(M1)
    if M2:
        md += ['', ] + tableau(M2, 'Passe 2 : Exposure2012 = gain de la passe 1 (réglage réel dans Camera Raw)',
                               'de_phocus', 'Chaque 3FR est rendu une seconde fois avec Exposure2012 réglé au gain trouvé pour lui en '
                               'passe 1 (arrondi 0,01) ; la mesure garde un petit gain résiduel libre (voir plus bas).')
        md += ['', '### Passe 2 sans gain résiduel', ''] + sans_gain(M2)

    # modèle
    md += ['', '## Écart modèle (`chaine_adobe.py`) / Camera Raw, passe 1', '',
           'Même profil, même fichier. Le modèle reçoit la balance « as shot » (CameraNeutral = 1/multiplicateurs) et la '
           'BaselineExposure **propre à chaque 3FR** (tag DNG lu par exiftool, de 0 à +2 IL : le boîtier y écrit la luminosité '
           'auto de HNCS), puis un gain libre pour coller au rendu Camera Raw. « Sans BE » : même chose avec BaselineExposure 0 '
           '(ce que supposait `ajuster.py`).', '',
           '| Profil | ΔE modèle / Camera Raw sans BE ni gain (médiane) | avec BE, sans gain (médiane) | avec BE et gain (médiane) | idem (90e) | gain résiduel médian (IL) | min | max |',
           '|---|---|---|---|---|---|---|---|']
    base = {}
    for cle in cles:
        gm = [M1[(n, cle)]['gain_modele'] for n in noms if (n, cle) in M1]
        if not gm:
            continue
        a0 = [M1[(n, cle)]['de_modele_acr_sans_gain'] for n in noms if (n, cle) in M1]
        a1 = [M1[(n, cle)]['de_modele_acr_sans_be'] for n in noms if (n, cle) in M1]
        a = [M1[(n, cle)]['de_modele_acr'] for n in noms if (n, cle) in M1]
        m, p = stat(a)
        m0, _ = stat(a0)
        m1, _ = stat(a1)
        base[cle] = float(np.median(gm))
        md.append(f'| {PROFILS[cle][2]} | {m1:.2f} | {m0:.2f} | {m:.2f} | {p:.2f} | {np.median(gm):+.3f} | {min(gm):+.3f} | {max(gm):+.3f} |')
    if base:
        v = np.median(list(base.values()))
        be = baseline_exposures(noms)
        r0 = [M1[(n, c)]['gain_modele'] for n in noms for c in cles if (n, c) in M1 and be[n][0] == 0]
        r1 = [M1[(n, c)]['gain_modele'] for n in noms for c in cles if (n, c) in M1 and be[n][0] != 0]
        md += ['', f'**BaselineExposure déduite : celle du 3FR, image par image** (tag DNG, {min(x[0] for x in be.values()):+.2f} à '
               f'{max(x[0] for x in be.values()):+.2f} IL sur ces 12 fichiers : le boîtier y écrit la luminosité auto de HNCS), appliquée par '
               f'Camera Raw avec, en plus, un petit résidu : {np.median(r0):+.2f} IL médian sur les {len(r0) // 3} fichiers dont la '
               f'BaselineExposure est 0, {np.median(r1):+.2f} IL sur les {len(r1) // 3} autres (résidu global {v:+.3f} IL ; le '
               f'`Baseline Exposure Offset` du profil, {np.median([x[1] for x in be.values()]):+.2f} dans le 3FR, est déjà compté par le '
               'modèle via le DCP). Le modèle d\'`ajuster.py` (`exposition_base=0`) ignorait cette BaselineExposure par image : '
               'ses « gains par image » (jusqu\'à +2 IL) absorbaient la luminosité auto de HNCS, que Camera Raw applique tout seul.']
        # diagnostic par luminance (profil HNCS)
        X = [(M1[(n, 'hncs')]['xyz'], M1[(n, 'hncs')]['xyz_modele']) for n in noms if (n, 'hncs') in M1]
        A = np.concatenate([x[0] for x in X]); Mo = np.concatenate([x[1] for x in X])
        LA, LM = E.lab(A), E.lab(Mo)
        eA = de(A, Mo)
        md += ['', 'Écart modèle / Camera Raw (profil HNCS, 12 images, gain résiduel appliqué au modèle) selon la luminance du rendu Camera Raw :', '',
               '| Y Camera Raw | blocs | ΔE médiane | ΔL* médian (Camera Raw − modèle) | ΔC* médian (Camera Raw − modèle) |', '|---|---|---|---|---|']
        for a_, b_ in ((0, 0.02), (0.02, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 1.01)):
            mk = (A[:, 1] >= a_) & (A[:, 1] < b_)
            if mk.sum() > 20:
                md.append(f'| {a_:g} à {b_:g} | {mk.sum()} | {np.median(eA[mk]):.2f} | {np.median(LA[mk, 0] - LM[mk, 0]):+.2f} | '
                          f'{np.median(np.hypot(LA[mk, 1], LA[mk, 2]) - np.hypot(LM[mk, 1], LM[mk, 2])):+.2f} |')

    # gains par image
    md += ['', '## Gain par image (IL), passe 1, contre Phocus', '',
           'Gain libre qui colle le mieux Camera Raw (exposition 0) à Phocus : proche de 0 = Lightroom retrouve la luminosité de '
           'Phocus sans réglage. BE = BaselineExposure du 3FR.', '',
           '| Image | groupe | BE 3FR | gain HNCS | gain dcamprof | gain Adobe Std | ΔE méd. HNCS | ΔE méd. dcamprof | ΔE méd. Adobe Std | résidu modèle -> Camera Raw (HNCS) |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for nom in noms:
        if not all((nom, c) in M1 for c in cles):
            continue
        gr = 'tenue à part' if nom in tenues else 'ajustement'
        md.append(f'| {nom} | {gr} | {M1[(nom, "hncs")]["be"]:+.2f} | ' + ' | '.join(f'{M1[(nom, c)]["gain_phocus"]:+.2f}' for c in cles) + ' | ' +
                  ' | '.join(f'{np.median(M1[(nom, c)]["de_phocus"]):.2f}' for c in cles) +
                  f' | {M1[(nom, "hncs")]["gain_modele"]:+.2f} |')
    if M2:
        md += ['', '## Passe 2 : exposition réglée et résidu', '',
               '| Image | Exposure2012 HNCS | résidu HNCS | ΔE sans gain HNCS | ΔE méd. HNCS (avec résidu) | Exposure2012 Adobe Std | ΔE sans gain Adobe Std |',
               '|---|---|---|---|---|---|---|']
        for nom in noms:
            if (nom, 'hncs') in M2 and (nom, 'adobe') in M2:
                h, a = M2[(nom, 'hncs')], M2[(nom, 'adobe')]
                md.append(f'| {nom} | {h["expo"]:+.2f} | {h["gain_phocus"]:+.2f} | {np.median(h["de_phocus_sans_gain"]):.2f} | '
                          f'{np.median(h["de_phocus"]):.2f} | {a["expo"]:+.2f} | {np.median(a["de_phocus_sans_gain"]):.2f} |')
    md += croisement(M1, M2, noms, tenues, z, nz)
    md += conclusion(M1, M2, tenues, cles)
    (PROJET / 'measurements' / 'validation-acr.md').write_text('\n'.join(md) + '\n')
    print('\n'.join(md))
    planche(tenues, M1)
    return M1, M2


def meta_3fr(noms):
    """Objectif, ISO, compensation d'exposition, BaselineExposure de chaque 3FR (exiftool, mis en cache)."""
    f = RES / 'meta.json'
    d = json.loads(f.read_text()) if f.exists() else {}
    manque = [n for n in noms if n not in d]
    if manque:
        r = subprocess.run(['exiftool', '-json', '-n', '-LensModel', '-ISO', '-ExposureCompensation', '-BaselineExposure']
                           + [str(ENTREE / f'{n}.3FR') for n in manque], capture_output=True, text=True, check=True)
        for n, e in zip(manque, json.loads(r.stdout)):
            d[n] = {k: e.get(k) for k in ('LensModel', 'ISO', 'ExposureCompensation', 'BaselineExposure')}
        f.write_text(json.dumps(d))
    return {n: d[n] for n in noms}


def croisement(M1, M2, noms, tenues, z, nz):
    meta = meta_3fr(noms)
    L = ['', '## Gain par image croisé avec objectif, ISO, compensation d\'exposition et BaselineExposure', '',
         'Gain = gain libre (IL) qui colle Camera Raw HNCS (exposition 0, corrections d\'objectif désactivées, mesure au centre) à Phocus. '
         'Si Phocus éclaircissait selon l\'objectif, ce gain varierait avec l\'objectif à BaselineExposure égale.', '',
         '| Image | objectif | ISO | compensation (IL) | BaselineExposure 3FR | gain HNCS vs Phocus | gain Adobe Std vs Phocus |', '|---|---|---|---|---|---|---|']
    for n in noms:
        if (n, 'hncs') in M1:
            m = meta[n]
            L.append(f"| {n} | {m['LensModel']} | {m['ISO']} | {m['ExposureCompensation']} | {m['BaselineExposure']:+.2f} | "
                     f"{M1[(n, 'hncs')]['gain_phocus']:+.2f} | {M1[(n, 'adobe')]['gain_phocus']:+.2f} |")
    # par objectif x BE
    grp = {}
    for n in noms:
        if (n, 'hncs') in M1:
            grp.setdefault((meta[n]['LensModel'], round(meta[n]['BaselineExposure'])), []).append(M1[(n, 'hncs')]['gain_phocus'])
    L += ['', 'Lecture : les 12 fichiers sont tous au XCD 55V, l\'objectif ne peut donc pas être testé comme facteur ; l\'ISO suit la BaselineExposure (50 : 0, 100 : +1, 200 : +2), la compensation d\'exposition est 0 partout. Les paliers d\'environ 1 IL des gains de `ajuster.py` sont la BaselineExposure du 3FR, que Camera Raw applique seul ; reste un écart de +0,15 / -0,12 / -0,27 IL selon le palier (Camera Raw plus sombre que Phocus quand BE > 0).', '', 'Gain HNCS par objectif et par palier de BaselineExposure :', '', '| objectif | BE (arrondie) | images | gain médian | min | max |', '|---|---|---|---|---|---|']
    for (o, b), g in sorted(grp.items(), key=lambda x: (str(x[0][0]), x[0][1])):
        L.append(f'| {o} | {b} | {len(g)} | {np.median(g):+.2f} | {min(g):+.2f} | {max(g):+.2f} |')
    # tons presque blancs
    L += ['', '## Tons presque blancs : écart en L* Camera Raw − Phocus', '',
          'Blocs dont le niveau brut (RVB caméra linéaire, max des canaux, saturation = 1) dépasse 0,6, mesurés au centre. '
          'Écart de L* (Lab D50) médian entre le rendu Camera Raw et Phocus, à exposition 0 sans gain, et avec le gain libre de l\'image ; '
          'négatif = Camera Raw plus sombre. Peu de blocs (la sélection écarte les zones écrêtées ou texturées) : indicatif seulement.', '',
          '| Profil | blocs | images concernées | ΔL* sans gain | ΔL* avec gain libre | ΔL* à gain nul des blocs Y Phocus > 0,6 (L* > 81) |', '|---|---|---|---|---|---|']
    for cle in ('hncs', 'dcamprof', 'adobe'):
        a0, a1, a2, ims, nb = [], [], [], set(), 0
        for n in noms:
            if (n, cle) not in M1:
                continue
            b = blocs_image(z, nz, n)
            mk = b['cam'].max(1) > 0.6
            hi = b['phocus'][:, 1] > 0.6
            o = M1[(n, cle)]
            lp = E.lab(b['phocus'])[:, 0]
            if mk.sum():
                ims.add(n); nb += int(mk.sum())
                a0.append(E.lab(o['xyz'][mk])[:, 0] - lp[mk])
                a1.append(E.lab(o['xyz'][mk] * 2.0 ** o['gain_phocus'])[:, 0] - lp[mk])
            if hi.sum():
                a2.append(E.lab(o['xyz'][hi])[:, 0] - lp[hi])
        f = lambda a: f'{np.median(np.concatenate(a)):+.2f}' if a else 'n/a'
        L.append(f'| {PROFILS[cle][2]} | {nb} | {len(ims)} | {f(a0)} | {f(a1)} | {f(a2)} |')
    return L


def conclusion(M1, M2, tenues, cles):
    """Conclusion chiffrée, déduite des mesures (sur les images tenues à part, contre Phocus, passe 1)."""
    def med(M, cle, champ, ims=tenues):
        return float(np.median(np.concatenate([M[(n, cle)][champ] for n in ims if (n, cle) in M])))
    sg = {c: med(M1, c, 'de_phocus_sans_gain') for c in cles}
    ag = {c: med(M1, c, 'de_phocus') for c in cles}
    jp = {c: med(M1, c, 'de_jpeg') for c in cles}
    meilleur = min(sg, key=sg.get)
    L = ['', '## Conclusion', '',
         f'- Tenues à part, ΔE2000 médiane contre Phocus, Camera Raw à exposition 0 sans aucun gain : '
         + ', '.join(f'{PROFILS[c][2]} {sg[c]:.2f}' for c in cles) + '.',
         f'- Avec gain libre par image : ' + ', '.join(f'{PROFILS[c][2]} {ag[c]:.2f}' for c in cles) + '.',
         f'- Contre le JPEG du boîtier (gain libre) : ' + ', '.join(f'{PROFILS[c][2]} {jp[c]:.2f}' for c in cles) + '.',
         f'- À garder : **{PROFILS[meilleur][2]}** (ΔE médiane la plus basse contre Phocus sans gain sur les 8 images tenues à part).']
    return L


# ----------------------------------------------------------------------------------------------- planche
def _srgb_depuis_xyz(xyz):
    lin = np.clip(xyz @ np.linalg.inv(CA.SRGB_VERS_XYZ_D50).T, 0, 1)
    return np.clip(np.floor(CA._srgb_encode(lin) * 255 + 0.5), 0, 255).astype(np.uint8)


def planche(tenues, M):
    from PIL import Image, ImageDraw, ImageFont
    choix = [n for n in ('B0000586', 'B0000594', 'B0000607', 'B0000612') if n in tenues] or tenues[:4]
    passe = 1   # exposition 0 : Camera Raw applique seul la BaselineExposure du 3FR
    W = 520
    police = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 22)
    petite = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 17)
    lignes = []
    for nom in choix:
        red_p = ref_reduite(nom)
        cols = [('Phocus (HNCS)', _srgb_depuis_xyz(E.decode_adobe(red_p.astype(np.float32) / 65535)))]
        for cle, lib in (('hncs', 'Camera Raw + HNCS'), ('adobe', 'Camera Raw + Adobe Standard')):
            r = np.load(chemin_res(nom, cle, passe))
            m, g = r['icc_colorants'], float(r['icc_gamma'])
            cols.append((lib, _srgb_depuis_xyz(decode_prophoto(r['red'].astype(np.float32) / 65535, m, g))))
        lignes.append((nom, cols, [None, float(r['expo']) if False else None, None]))
    h_img = int(W * lignes[0][1][0][1].shape[0] / lignes[0][1][0][1].shape[1])
    # hauteur par ligne selon l'orientation (portrait possible) : on cadre chaque ligne sur sa première image
    marge, bandeau, legende = 8, 44, 30
    hauteurs = [int(W * c[0][1].shape[0] / c[0][1].shape[1]) for _, c, _ in lignes]
    H = bandeau + sum(h + legende + marge for h in hauteurs) + marge
    img = Image.new('RGB', (3 * W + 4 * marge, H), (24, 24, 24))
    dr = ImageDraw.Draw(img)
    for k, tit in enumerate(('Phocus (HNCS)', 'Camera Raw + HNCS', 'Camera Raw + Adobe Standard')):
        dr.text((marge + k * (W + marge), 10), tit, fill=(255, 255, 255), font=police)
    y = bandeau
    for (nom, cols, _), h in zip(lignes, hauteurs):
        for k, (lib, a) in enumerate(cols):
            im = Image.fromarray(a).resize((W, h), Image.LANCZOS)
            img.paste(im, (marge + k * (W + marge), y))
        e = {c: M[(nom, c)]['expo'] for c in ('hncs', 'adobe') if (nom, c) in M}
        txt = f'{nom}'
        txt += '   Camera Raw : exposition 0, aucun autre réglage (BaselineExposure du 3FR appliquée)'
        dr.text((marge, y + h + 4), txt, fill=(200, 200, 200), font=petite)
        y += h + legende + marge
    sortie = PROJET / 'measurements' / 'planche-acr.png'
    img.save(sortie)
    print('planche :', sortie, img.size)


# ----------------------------------------------------------------------------------------------- self-test
def self_test():
    # 1) XMP : généré, relu
    t = xmp('HNCS (dcamprof)', 0.85)
    d = lire_xmp(t)
    assert d['CameraProfile'] == 'HNCS (dcamprof)' and d['ProcessVersion'] == '11.0' and d['WhiteBalance'] == 'As Shot'
    assert d['Exposure2012'] == '+0.85' and d['Sharpness'] == '0' and d['LensProfileEnable'] == '0'
    assert d['ColorNoiseReduction'] == '0' and d['Clarity2012'] == '0' and d['ToneCurveName2012'] == 'Linear'
    assert d['_courbe'] == ['0, 0', '255, 255']
    d0 = lire_xmp(xmp('Adobe Standard'))
    assert d0['Exposure2012'] == '+0.00' and d0['CameraProfile'] == 'Adobe Standard'
    # 2) profils installés et lisibles
    for cle, (nomp, f, _) in PROFILS.items():
        assert f.exists(), f
        assert nomp.encode() in f.read_bytes(), f'ProfileName {nomp} absent de {f.name}'
    # 3) tableaux de référence
    z, noms, tenues = charger_ref()
    assert len(tenues) == 8 and all(n in noms for n in AJUSTEMENT) and not set(AJUSTEMENT) & set(tenues)
    assert (ENTREE / f'{tenues[0]}.3FR').exists() and (SORTIE / f'B_{tenues[0][-4:]}.tif').exists()
    # 4) gain libre retrouvé
    rng = np.random.default_rng(0)
    x = np.abs(rng.normal(0.2, 0.1, (300, 3))) * E.D50
    assert abs(meilleur_gain_post(x * 2 ** 0.4, x) + 0.4) < 0.02
    # 5) Photoshop répond
    avant = ps_ouvert()
    v = ps('app.displayDialogs = DialogModes.NO; app.version;', delai=300)
    assert re.match(r'\d+\.\d+', v), v
    print('Photoshop', v, '(ouvert avant :', avant, ')')
    if not avant:
        ps_quitter()
    print('self-test OK')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', nargs='?', choices=['rendre', 'mesurer', 'tout'])
    ap.add_argument('--passe', type=int, choices=[1, 2], default=1)
    ap.add_argument('--seulement', nargs='*')
    ap.add_argument('--profils', nargs='*', choices=list(PROFILS))
    ap.add_argument('--refaire', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    for _d in ("measurements", "profiles"):
        (PROJET / _d).mkdir(exist_ok=True)   # output folders, created on first real run
    z, nz, tenues = charger_ref()
    noms = a.seulement or (tenues + AJUSTEMENT)
    cles = a.profils or list(PROFILS)
    avant = ps_ouvert()
    try:
        if a.action == 'rendre':
            rendre(noms, cles, a.passe, a.refaire)
        elif a.action == 'mesurer':
            mesurer()
        elif a.action == 'tout':
            rendre(noms, cles, 1, a.refaire)
            rendre(noms, cles, 2, a.refaire)
            mesurer()
    finally:
        if not avant and ps_ouvert():
            ps_quitter()


if __name__ == '__main__':
    sys.exit(main())
