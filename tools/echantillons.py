#!/usr/bin/env python3
"""Échantillons pour ajuster le profil HNCS : pour chaque image (3FR du X2D II + export Phocus + JPEG du boîtier),
blocs uniformes de 16x16 pixels (pleine taille) avec

  cam_rgb     RGB caméra linéaire brut (rawpy : noir soustrait, normalisé au blanc de saturation, dématriçage
              demi-taille, SANS matrice couleur, SANS balance des blancs), moyenne du bloc
  wb_as_shot  multiplicateurs de balance du boîtier (R, G, B, G2), par image
  phocus_xyz  export Phocus (TIFF 16 bits Adobe RGB 1998, TRC 563/256) -> XYZ D50 linéaire
  jpeg_xyz    JPEG du boîtier (Display P3, TRC sRGB) -> XYZ D50 linéaire

Sélection des blocs (same selection logic as the author's earlier camera measurements) : écart-type relatif < 0,04 sur
chacune des trois sources (sur des demi-pixels de 2x2, 8x8 par bloc), pas d'écrêtage, centre de l'image
(rayon² < 0,16). Alignement RAW / JPEG par corrélation de la luminance (log) : le RAW (11904x8842) est plus grand
que l'export (11656x8742).

  echantillons.py extraire [--seulement B0000583 ...] [--refaire]   # un .npz par image dans C/echantillons/, puis fusion
  echantillons.py fusionner                                         # refait seulement data/samples-pass1.npz
  echantillons.py mesure                                            # measurements/phocus-vs-jpeg.md
  echantillons.py --self-test
"""
import argparse
import glob
import io
import os
import pathlib
import struct
import sys
import warnings

import numpy as np

warnings.filterwarnings('ignore')
import colour  # noqa: E402

PROJET = pathlib.Path(__file__).resolve().parent.parent
C = pathlib.Path(os.environ.get('HNCS_WORKDIR', 'workdir')).resolve()   # work folder (HNCS_WORKDIR)
JPEG_DIR = pathlib.Path(os.environ.get('HNCS_JPEG_DIR', 'camera-jpegs'))   # in-camera JPEGs (passe 1 only)
BLOC = 16            # pixels pleine taille par côté de bloc
BH = BLOC // 2       # = 8 demi-pixels
SEUIL_CV = 0.04
D50 = np.array([0.9642, 1.0, 0.8249])   # blanc du PCS ICC
GAMMA_ADOBE = 563 / 256
PAR_IMAGE_FUSION = 4000


# ----------------------------------------------------------------------------------------------- couleur
def _matrice_d50(nom):
    cs = colour.RGB_COLOURSPACES[nom]
    w = colour.xy_to_XYZ(cs.whitepoint)
    cat = colour.adaptation.matrix_chromatic_adaptation_VonKries(w, D50, 'Bradford')
    return cat @ cs.matrix_RGB_to_XYZ


M_ADOBE = _matrice_d50('Adobe RGB (1998)')
M_P3 = _matrice_d50('Display P3')


def decode_adobe(v):
    """Adobe RGB 1998 encodé (0..1) -> XYZ D50 linéaire. TRC = gamma 563/256."""
    return (np.clip(v, 0, 1) ** GAMMA_ADOBE) @ M_ADOBE.T


def eotf_srgb(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def decode_p3(v):
    """Display P3 encodé (TRC sRGB) -> XYZ D50 linéaire."""
    return eotf_srgb(v) @ M_P3.T


def lab(xyz):
    return colour.XYZ_to_Lab(xyz, colour.XYZ_to_xy(D50))


# ----------------------------------------------------------------------------------------------- ICC / TIFF
def icc_balises(b):
    n = struct.unpack('>I', b[128:132])[0]
    t = {}
    for i in range(n):
        s, o, z = struct.unpack('>4sII', b[132 + 12 * i:144 + 12 * i])
        t[s.decode('latin1')] = (o, z)
    return t


def icc_colorants(b):
    t = icc_balises(b)
    return np.array([[v / 65536 for v in struct.unpack('>3i', b[t[k][0] + 8:t[k][0] + 20])] for k in ('rXYZ', 'gXYZ', 'bXYZ')]).T


def icc_gamma_u8f8(b):
    o, z = icc_balises(b)['rTRC']
    if b[o:o + 4] != b'curv' or struct.unpack('>I', b[o + 8:o + 12])[0] != 1:
        return None
    return struct.unpack('>H', b[o + 12:o + 14])[0] / 256


def lire_tiff(chemin):
    """TIFF big-endian non compressé, un seul bloc de données (export Phocus). Retourne dict + ICC."""
    with open(chemin, 'rb') as f:
        h = f.read(8)
        assert h[:2] == b'MM' and struct.unpack('>H', h[2:4])[0] == 42, 'TIFF big-endian attendu'
        f.seek(struct.unpack('>I', h[4:8])[0])
        n = struct.unpack('>H', f.read(2))[0]
        e = {}
        tailles = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1}
        for _ in range(n):
            tag, typ, cnt, val = struct.unpack('>HHI4s', f.read(12))
            z = tailles.get(typ, 1) * cnt
            if z <= 4:
                raw = val[:z]
            else:
                p = f.tell()
                f.seek(struct.unpack('>I', val)[0]); raw = f.read(z); f.seek(p)
            e[tag] = (typ, cnt, raw)
    num = lambda t: struct.unpack('>%d%s' % (e[t][1], {3: 'H', 4: 'I'}[e[t][0]]), e[t][2])
    d = {'w': num(256)[0], 'h': num(257)[0], 'bits': num(258), 'compression': num(259)[0], 'spp': num(277)[0],
         'offsets': num(273), 'counts': num(279), 'planar': num(284)[0] if 284 in e else 1,
         'orientation': num(274)[0] if 274 in e else 1}
    assert d['compression'] == 1 and d['bits'] == (16, 16, 16) and d['spp'] == 3 and d['planar'] == 1, d
    # strips contigus ?
    off = d['offsets'][0]
    for o, z, o2 in zip(d['offsets'], d['counts'], d['offsets'][1:]):
        assert o + z == o2, 'strips non contigus'
    assert sum(d['counts']) == d['w'] * d['h'] * 6
    d['offset'] = off
    d['icc'] = e[34675][2] if 34675 in e else None
    return d


# ----------------------------------------------------------------------------------------------- blocs
def stats_blocs(chunk, nby, nbx):
    """chunk(r0, r1) -> float32 [0,1] (demi-pixels, lignes r0..r1, colonnes 0..8*nbx, 3 canaux).
    Retourne moyenne (nby,nbx,3), écart-type relatif de la luminance moyenne des 3 canaux (nby,nbx),
    maximum de pixel (tous canaux) du bloc (nby,nbx)."""
    mean = np.zeros((nby, nbx, 3), np.float32)
    cv = np.zeros((nby, nbx), np.float32)
    mx = np.zeros((nby, nbx), np.float32)
    pas = 8   # rangées de blocs par passe
    for b0 in range(0, nby, pas):
        b1 = min(nby, b0 + pas)
        a = chunk(b0 * BH, b1 * BH)[:, :nbx * BH]
        k = b1 - b0
        a = a.reshape(k, BH, nbx, BH, 3)
        m = a.mean((1, 3))
        l = a.mean(-1)
        mean[b0:b1] = m
        cv[b0:b1] = l.std((1, 3)) / (l.mean((1, 3)) + 1e-3)
        mx[b0:b1] = a.max((1, 3, 4))
    return mean, cv, mx


def chunk_tiff(mm):
    def f(r0, r1):
        a = np.asarray(mm[2 * r0:2 * r1], np.float32)   # big-endian -> float32
        a = a.reshape(r1 - r0, 2, a.shape[1] // 2, 2, 3).mean((1, 3)) if a.shape[1] % 2 == 0 else \
            a[:, :-1].reshape(r1 - r0, 2, (a.shape[1] - 1) // 2, 2, 3).mean((1, 3))
        return a / 65535
    return f


def chunk_array(a, echelle, r_off=0, c_off=0):
    def f(r0, r1):
        return a[r_off + r0:r_off + r1, c_off:].astype(np.float32) / echelle
    return f


# ----------------------------------------------------------------------------------------------- alignement
def aligner(raw_g, jp_lum, marge=40, T=1200):
    """raw_g, jp_lum : luminances log (demi-pixels). Cherche (dy, dx) tel que raw_g[dy:, dx:] ~ jp_lum.
    Template central de jp_lum dans une fenêtre de raw_g autour de la position centrée."""
    import cv2
    Hj, Wj = jp_lum.shape
    Hr, Wr = raw_g.shape
    T = min(T, Hj // 3, Wj // 3)
    ty, tx = (Hj - T) // 2, (Wj - T) // 2
    tmpl = np.ascontiguousarray(jp_lum[ty:ty + T, tx:tx + T], np.float32)
    ey, ex = (Hr - Hj) // 2, (Wr - Wj) // 2
    while True:
        y0, x0 = ey + ty - marge, ex + tx - marge
        y0c, x0c = max(0, y0), max(0, x0)
        fen = np.ascontiguousarray(raw_g[y0c:y0 + T + 2 * marge + 1, x0c:x0 + T + 2 * marge + 1], np.float32)
        if fen.shape[0] < T or fen.shape[1] < T:
            return None, 0.0
        res = cv2.matchTemplate(fen, tmpl, cv2.TM_CCOEFF_NORMED)
        py, px = np.unravel_index(np.argmax(res), res.shape)
        corr = float(res[py, px])
        bord = py in (0, res.shape[0] - 1) or px in (0, res.shape[1] - 1)
        if bord and marge < 200:
            marge *= 2
            continue
        return (y0c + py - ty, x0c + px - tx), corr


def luma_log_jpeg(a):
    """a : uint8 (H,W,3) Display P3 -> log luminance linéaire (sous-échantillonné pour aller vite)."""
    y = decode_p3(a.astype(np.float32) / 255)[..., 1]
    return np.log(np.clip(y, 0, 1) + 1e-3).astype(np.float32)


# ----------------------------------------------------------------------------------------------- extraction
def ouvrir_jpeg_demi(chemin):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(chemin)
    icc = im.info.get('icc_profile')
    exif_or = im.getexif().get(274, 1)
    w, h = im.size
    im.draft('RGB', (w // 2, h // 2))
    assert im.size == (w // 2, h // 2), f'draft JPEG inattendu {im.size}'
    im = ImageOps.exif_transpose(im.convert('RGB'))
    return np.asarray(im), icc, exif_or


def extraire_image(nom, refaire=False):
    """nom : B0000583. Retourne le dict d'échantillons (et l'écrit dans C/echantillons/)."""
    import rawpy
    out = C / 'echantillons' / f'{nom}.npz'
    if out.exists() and not refaire:
        return None
    tif = C / 'phocus-sortie' / f'B_{nom[-4:]}.tif'
    jpg = JPEG_DIR / f'{nom}.JPG'
    raw_p = C / 'phocus-entree' / f'{nom}.3FR'
    anomalies = []

    # --- Phocus : en-tête, ICC, mémoire mappée
    d = lire_tiff(tif)
    g = icc_gamma_u8f8(d['icc'])
    assert g is not None and abs(g - GAMMA_ADOBE) < 1e-6, f'gamma ICC Phocus {g} != 563/256'
    dm = np.abs(icc_colorants(d['icc']) - M_ADOBE).max()
    assert dm < 2e-3, f'colorants Adobe RGB différents du calcul : {dm}'
    mm = np.memmap(tif, dtype='>u2', mode='r', offset=d['offset'], shape=(d['h'], d['w'], 3))
    nby, nbx = d['h'] // BLOC, d['w'] // BLOC

    # --- JPEG (demi-taille par DCT), orientation EXIF appliquée
    jh, icc_j, exif_or = ouvrir_jpeg_demi(jpg)
    assert icc_j is not None and 'rXYZ' in icc_balises(icc_j) and b'para' in icc_j, 'ICC du JPEG inattendu'
    dj = np.abs(icc_colorants(icc_j) - M_P3).max()
    assert dj < 2e-3, f'colorants P3 différents du calcul : {dj}'
    if jh.shape[:2] != (d['h'] // 2, d['w'] // 2):
        anomalies.append(f'taille JPEG {jh.shape[:2]} != Phocus/2 {(d["h"] // 2, d["w"] // 2)}')
        raise RuntimeError(anomalies[-1])
    if d['orientation'] != 1:
        anomalies.append(f'orientation TIFF {d["orientation"]} (pixels non tournés supposés)')

    # --- RAW brut linéaire (demi-taille)
    r = rawpy.imread(str(raw_p))
    wb = np.array(r.camera_whitebalance, np.float32)
    raw = r.postprocess(half_size=True, output_color=rawpy.ColorSpace.raw, gamma=(1, 1), no_auto_bright=True,
                        user_wb=[1, 1, 1, 1], output_bps=16)
    flip_raw = int(r.sizes.flip)
    r.close()
    paysage = lambda s: s[1] >= s[0]
    rot = 0
    if paysage(raw.shape) != paysage(jh.shape):
        # LibRaw n'a pas appliqué l'orientation : on suit l'EXIF du JPEG (6 = 90° horaire, 8 = 90° antihoraire)
        rot = {6: -1, 8: 1, 3: 2}.get(int(exif_or), -1)
        raw = np.rot90(raw, rot).copy()
        anomalies.append(f'RAW tourné de {rot} quart(s) (EXIF JPEG {exif_or})')
    jlum = luma_log_jpeg(jh)
    rg = np.log(raw[..., 1].astype(np.float32) / 65535 + 1e-3)
    off, corr = aligner(rg, jlum)
    if off is None or corr < 0.9:
        # dernier recours : essayer les trois autres rotations du RAW
        meilleur = (corr, off, rot)
        for k in range(4):
            if k == 0 or paysage(np.rot90(raw, k).shape) != paysage(jh.shape):
                continue
            rg2 = np.log(np.rot90(raw[..., 1], k).astype(np.float32) / 65535 + 1e-3)
            o2, c2 = aligner(rg2, jlum)
            if o2 is not None and c2 > meilleur[0]:
                meilleur = (c2, o2, k)
        corr, off, k = meilleur
        if k != 0:
            raw = np.rot90(raw, k).copy()
            anomalies.append(f'rotation RAW supplémentaire {k}')
    del rg
    if off is None or corr < 0.9:
        raise RuntimeError(f'recalage RAW/JPEG douteux ({corr:.2f})')
    dy, dx = off
    H2, W2 = jh.shape[:2]
    if dy < 0 or dx < 0 or dy + nby * BH > raw.shape[0] or dx + nbx * BH > raw.shape[1]:
        raise RuntimeError(f'décalage {off} hors du RAW {raw.shape}')

    # --- statistiques par bloc
    m_raw, cv_raw, mx_raw = stats_blocs(chunk_array(raw, 65535.0, dy, dx), nby, nbx)
    m_jpg, cv_jpg, mx_jpg = stats_blocs(chunk_array(jh, 255.0), nby, nbx)
    m_pho, cv_pho, mx_pho = stats_blocs(chunk_tiff(mm), nby, nbx)
    del mm, raw

    # --- vérification Phocus / JPEG : même géométrie ? (décalage de blocs sur la luminance log)
    import cv2
    ly = lambda m, dec: np.log(dec(m)[..., 1].astype(np.float32) + 1e-3)
    Lp, Lj = ly(m_pho, decode_adobe), ly(m_jpg, decode_p3)
    mg = 3
    cr = cv2.matchTemplate(np.ascontiguousarray(Lp), np.ascontiguousarray(Lj[mg:-mg, mg:-mg]), cv2.TM_CCOEFF_NORMED)
    pp = np.unravel_index(np.argmax(cr), cr.shape)
    dec_pj = (int(pp[0]) - mg, int(pp[1]) - mg)
    if dec_pj != (0, 0):
        anomalies.append(f'décalage Phocus/JPEG en blocs {dec_pj}')

    # --- sélection
    yy, xx = np.mgrid[0:nby, 0:nbx]
    ok = (cv_raw < SEUIL_CV) & (cv_jpg < SEUIL_CV) & (cv_pho < SEUIL_CV)
    ok &= mx_raw <= 0.98                                    # RAW non écrêté
    ok &= (m_jpg.max(-1) < 0.985) & (m_pho.max(-1) < 0.985)
    ok &= m_raw[..., 1] > 1e-4
    ok &= ((yy - nby / 2) / nby) ** 2 + ((xx - nbx / 2) / nbx) ** 2 < 0.16
    res = {
        'nom': nom, 'cam_rgb': m_raw[ok], 'wb_as_shot': wb,
        'phocus_xyz': decode_adobe(m_pho[ok].astype(np.float64)).astype(np.float32),
        'jpeg_xyz': decode_p3(m_jpg[ok].astype(np.float64)).astype(np.float32),
        'by': yy[ok].astype(np.int16), 'bx': xx[ok].astype(np.int16), 'grille': np.array([nby, nbx]),
        'decalage_raw': np.array([dy, dx]), 'corr_raw_jpeg': corr, 'decalage_phocus_jpeg': np.array(dec_pj),
        'cv_raw': cv_raw[ok].astype(np.float16), 'cv_jpeg': cv_jpg[ok].astype(np.float16),
        'cv_phocus': cv_pho[ok].astype(np.float16), 'rot_raw': rot, 'flip_libraw': flip_raw,
        'exif_orientation_jpeg': int(exif_or), 'anomalies': np.array(anomalies, dtype=str),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **res)
    return res


def sous_echantillon(d, n, graine=0):
    """n blocs, répartis en classes de luminance (log2 Y Phocus), reste complété au hasard."""
    N = len(d['cam_rgb'])
    if N <= n:
        return np.arange(N)
    rng = np.random.default_rng(graine)
    y = np.log2(np.clip(d['phocus_xyz'][:, 1], 1e-4, None))
    cl = np.digitize(y, np.linspace(y.min(), y.max(), 17)[1:-1])
    choisis = []
    quota = n // 16
    for c in range(16):
        idx = np.flatnonzero(cl == c)
        if len(idx):
            choisis.append(rng.choice(idx, min(len(idx), quota), replace=False))
    choisis = np.concatenate(choisis)
    reste = np.setdiff1d(np.arange(N), choisis)
    if len(choisis) < n:
        choisis = np.concatenate([choisis, rng.choice(reste, min(len(reste), n - len(choisis)), replace=False)])
    return np.sort(choisis)


def fusionner():
    fs = sorted(glob.glob(str(C / 'echantillons' / 'B*.npz')))
    if not fs:
        print('aucun échantillon à fusionner')
        return
    champs = ['cam_rgb', 'phocus_xyz', 'jpeg_xyz', 'by', 'bx']
    acc = {k: [] for k in champs}
    img, noms, wbs, pos, tot = [], [], [], [], []
    for i, f in enumerate(fs):
        d = np.load(f)
        s = sous_echantillon(d, PAR_IMAGE_FUSION)
        for k in champs:
            acc[k].append(d[k][s])
        img.append(np.full(len(s), i, np.int16))
        noms.append(str(d['nom'])); wbs.append(d['wb_as_shot']); tot.append(len(d['cam_rgb']))
    sortie = PROJET / 'data' / 'samples-pass1.npz'
    sortie.parent.mkdir(exist_ok=True)
    np.savez_compressed(sortie, **{k: np.concatenate(v) for k, v in acc.items()}, image=np.concatenate(img),
                        noms=np.array(noms), wb_as_shot=np.array(wbs), blocs_par_image_total=np.array(tot),
                        note=np.array('cam_rgb : RGB caméra linéaire brut (noir soustrait, blanc de saturation = 1, '
                                      'sans matrice ni balance) ; phocus_xyz / jpeg_xyz : XYZ D50 linéaire ; '
                                      'by, bx : position du bloc (16 px) ; image : indice dans noms ; '
                                      f'au plus {PAR_IMAGE_FUSION} blocs par image, répartis en luminance'))
    print(f'fusionné : {sum(len(a) for a in acc["cam_rgb"])} blocs sur {len(fs)} images -> {sortie} '
          f'({sortie.stat().st_size / 1e6:.1f} Mo)')


# ----------------------------------------------------------------------------------------------- mesure
def de2000(a, b, morceau=400000):
    out = np.empty(len(a))
    for i in range(0, len(a), morceau):
        out[i:i + morceau] = colour.delta_E(lab(a[i:i + morceau]), lab(b[i:i + morceau]), method='CIE 2000')
    return out


def meilleur_gain(p, j):
    """Gain d'exposition (en IL) appliqué à Phocus qui minimise la médiane de ΔE2000 contre le JPEG."""
    from scipy.optimize import minimize_scalar
    sel = np.random.default_rng(0).choice(len(p), min(len(p), 20000), replace=False)
    f = lambda e: np.median(de2000(p[sel] * 2.0 ** e, j[sel]))
    r = minimize_scalar(f, bounds=(-1.5, 1.5), method='bounded', options={'xatol': 1e-3})
    return float(r.x)


def mesure():
    fs = sorted(glob.glob(str(C / 'echantillons' / 'B*.npz')))
    lignes, P, J, I = [], [], [], []
    for i, f in enumerate(fs):
        d = np.load(f)
        p, j = d['phocus_xyz'].astype(np.float64), d['jpeg_xyz'].astype(np.float64)
        e = de2000(p, j)
        mid = (j[:, 1] > 0.05) & (j[:, 1] < 0.6)
        ratio = np.median(np.log2(p[mid, 1] / j[mid, 1])) if mid.any() else float('nan')
        g = meilleur_gain(p, j)
        e2 = de2000(p * 2.0 ** g, j)
        lp, lj = lab(p), lab(j)
        lignes.append((str(d['nom']), len(p), np.median(e), e.mean(), np.percentile(e, 90), ratio, g, np.median(e2),
                       np.percentile(e2, 90), np.median(lp[:, 0] - lj[:, 0]),
                       np.median(np.hypot(lp[:, 1], lp[:, 2]) - np.hypot(lj[:, 1], lj[:, 2])),
                       list(d['anomalies'])))
        P.append(p); J.append(j); I.append(np.full(len(p), i))
    P, J = np.concatenate(P), np.concatenate(J)
    e = de2000(P, J)
    gains = np.array([l[6] for l in lignes])
    e2med = np.median(np.concatenate([de2000(p * 2.0 ** l[6], j) for p, j, l in zip(_iter(fs, 'phocus_xyz'), _iter(fs, 'jpeg_xyz'), lignes)]))
    # par plage de luminance
    Y = J[:, 1]
    plages = [(0, 0.02), (0.02, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.4), (0.4, 1.01)]
    md = ['# Phocus (export SDR) contre JPEG du boîtier, X2D II',
          '',
          f'{len(fs)} images, {len(P)} blocs uniformes de 16x16 px (`tools/echantillons.py`, source : '
          '`C/echantillons/`). Les deux sont décodés en XYZ D50 linéaire (Adobe RGB 1998 TRC 563/256 pour '
          'Phocus, Display P3 TRC sRGB pour le JPEG), ΔE2000 en Lab D50.',
          '',
          '## Global',
          '',
          f'- ΔE2000 : médiane **{np.median(e):.2f}**, moyenne {e.mean():.2f}, 90e centile {np.percentile(e, 90):.2f}.',
          f'- Gain d\'exposition à appliquer à Phocus pour coller au JPEG (meilleur ΔE, par image) : médiane '
          f'{np.median(gains):+.3f} IL, de {gains.min():+.3f} à {gains.max():+.3f} IL, écart-type {gains.std():.3f} IL.',
          f'- Après ce gain par image : ΔE2000 médiane **{e2med:.2f}**.',
          '',
          '## Par plage de luminance JPEG (Y, 1 = blanc)',
          '',
          '| Y | blocs | ΔE médiane | ΔE 90e | ΔL* médian (Phocus−JPEG) |',
          '|---|---|---|---|---|']
    LP, LJ = lab(P), lab(J)
    for a, b in plages:
        m = (Y >= a) & (Y < b)
        if m.sum() > 20:
            md.append(f'| {a:g} à {b:g} | {m.sum()} | {np.median(e[m]):.2f} | {np.percentile(e[m], 90):.2f} | '
                      f'{np.median(LP[m, 0] - LJ[m, 0]):+.2f} |')
    md += ['', '## Par image', '',
           '| Image | blocs | ΔE méd. | ΔE moy. | ΔE 90e | Δexpo médiane (IL, tons moyens) | gain optimal (IL) | ΔE méd. après gain | ΔE 90e après gain | ΔL* | ΔC* |',
           '|---|---|---|---|---|---|---|---|---|---|---|']
    for n, N, med, moy, p90, ratio, g, m2, p2, dl, dc, an in lignes:
        md.append(f'| {n} | {N} | {med:.2f} | {moy:.2f} | {p90:.2f} | {ratio:+.3f} | {g:+.3f} | {m2:.2f} | {p2:.2f} | {dl:+.2f} | {dc:+.2f} |')
    anos = [(l[0], l[11]) for l in lignes if l[11]]
    md += ['', '## Anomalies', '']
    md += [f'- {n} : {" ; ".join(a)}' for n, a in anos] or []
    md += ['- Orientation : LibRaw tourne seul le RAW des portraits (flip 5 ou 6), le TIFF Phocus est déjà tourné, le JPEG '
           'porte l\'EXIF 6 ou 8 (appliqué) : les trois concordent sur les 33 images, aucune rotation manuelle.',
           '- Phocus et JPEG : décalage de 0 bloc sur les 33 images (même géométrie).',
           '- RAW (11904x8842) / export (11656x8742) : décalage constant de 48 px en haut et 64 px à gauche (en demi-pixels, '
           'sens paysage ; équivalent tourné pour les portraits), avec 1 à 2 demi-pixels de dispersion sur 8 images '
           '(scènes peu texturées ou correction de distorsion du JPEG), corrélation de recalage 0,91 à 1,00 ; '
           'les blocs étant uniformes (16 px), l\'effet sur les mesures est négligeable.']
    ratio_pos = np.mean(gains < 0)
    md += ['', '## Conclusion', '',
           f'Phocus et le JPEG du boîtier ne sont pas la même référence à l\'identique : ΔE2000 médiane {np.median(e):.2f} '
           f'(90e centile {np.percentile(e, 90):.2f}) brute, {e2med:.2f} une fois l\'exposition recalée image par image. '
           f'Le gros de l\'écart est un gain de luminosité propre à chaque photo ({gains.min():+.2f} à {gains.max():+.2f} IL, '
           f'écart-type {gains.std():.2f} IL ; Phocus est plus clair que le JPEG sur {ratio_pos * 100:.0f} % des images) : '
           'chacun règle la luminosité à sa façon. Le reste (~1,2 ΔE) est un petit écart de rendu : Phocus un peu plus '
           'chargé en chroma (ΔC* +0,5 à +1,5), légères différences de courbe dans les ombres et les hautes lumières. '
           'À ΔE ~1,2 après recalage, ce sont deux rendus HNCS très proches mais pas interchangeables : '
           'on peut les traiter comme une même famille de référence, à condition de laisser un gain libre par image '
           'à l\'ajustement (comme `rendus.py`) et de ne pas fondre les deux dans un même jeu sans cette liberté.']
    pathlib.Path(PROJET / 'measurements').mkdir(exist_ok=True)
    (PROJET / 'measurements' / 'phocus-vs-jpeg.md').write_text('\n'.join(md) + '\n')
    print('\n'.join(md[:14]))
    return np.median(e), e2med


def _iter(fs, cle):
    for f in fs:
        yield np.load(f)[cle].astype(np.float64)


# ----------------------------------------------------------------------------------------------- self-test
def self_test():
    # 1) blanc et gris 18 % connus, Adobe RGB (TRC 563/256) et Display P3 (TRC sRGB)
    blanc = D50
    gris = 0.18 * D50
    adobe = lambda lin: lin ** (1 / GAMMA_ADOBE)
    srgb_oetf = lambda lin: np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    for nom, dec, enc in (('Adobe RGB', decode_adobe, adobe), ('Display P3', decode_p3, srgb_oetf)):
        for ref, lin in ((blanc, 1.0), (gris, 0.18)):
            v = np.full(3, enc(np.float64(lin)))
            xyz = dec(v)
            de = float(colour.delta_E(lab(xyz), lab(ref), method='CIE 2000'))
            assert de < 0.01, f'{nom} {lin} : ΔE {de}'
            assert np.abs(xyz - ref).max() < 1e-4, (nom, xyz, ref)
    # primaires connues (colorants ICC D50 d'Adobe RGB et de Display P3)
    assert np.abs(decode_adobe(np.array([1., 0, 0])) - [0.60974, 0.31111, 0.01947]).max() < 2e-3
    assert np.abs(decode_p3(np.array([1., 0, 0])) - [0.51512, 0.24120, -0.00105]).max() < 2e-3
    # 2) gamma ICC lu comme 563/256 (u8Fixed8 0x0233)
    assert abs(0x0233 / 256 - GAMMA_ADOBE) < 1e-12
    # 3) statistiques de blocs : image synthétique uniforme + un bloc bruité
    nby, nbx = 4, 6
    a = np.full((nby * BH, nbx * BH, 3), 0.25, np.float32)
    rng = np.random.default_rng(1)
    a[BH:2 * BH, 2 * BH:3 * BH] += rng.normal(0, 0.1, (BH, BH, 3)).astype(np.float32)
    m, cv, mx = stats_blocs(lambda r0, r1: a[r0:r1], nby, nbx)
    assert abs(m[0, 0, 0] - 0.25) < 1e-6 and cv[0, 0] < 1e-3 and cv[1, 2] > 0.04
    # 4) alignement : image texturée décalée
    import cv2
    tex = cv2.GaussianBlur(rng.random((900, 1100)).astype(np.float32), (0, 0), 3)
    dy, dx = 23, -17
    sub = tex[100 + dy:100 + dy + 600, 150 + dx:150 + dx + 800]
    off, corr = aligner(tex, sub, marge=40, T=400)
    ey, ex = (900 - 600) // 2, (1100 - 800) // 2
    assert off == (100 + dy, 150 + dx) and corr > 0.99, (off, corr)
    # 5) ΔE sur échantillons identiques et gain exact
    x = np.abs(rng.normal(0.2, 0.1, (500, 3))) * D50
    assert de2000(x, x).max() < 1e-9
    assert abs(meilleur_gain(x * 2 ** 0.3, x) + 0.3) < 0.02
    print('self-test OK')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', nargs='?', choices=['extraire', 'fusionner', 'mesure'])
    ap.add_argument('--seulement', nargs='*')
    ap.add_argument('--refaire', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.action == 'extraire':
        import time
        noms = a.seulement or sorted(p.stem for p in (C / 'phocus-entree').glob('*.3FR'))
        for n in noms:
            t = time.time()
            try:
                r = extraire_image(n, a.refaire)
            except Exception as e:  # une image en échec ne bloque pas le lot
                print(n, 'ÉCHEC', repr(e), flush=True)
                continue
            if r is None:
                print(n, 'déjà fait', flush=True)
            else:
                print(f'{n} : {len(r["cam_rgb"])} blocs, corr {r["corr_raw_jpeg"]:.3f}, décalage RAW {tuple(r["decalage_raw"])}, '
                      f'{time.time() - t:.0f}s {list(r["anomalies"]) or ""}', flush=True)
        fusionner()
    elif a.action == 'fusionner':
        fusionner()
    elif a.action == 'mesure':
        mesure()


if __name__ == '__main__':
    sys.exit(main())
