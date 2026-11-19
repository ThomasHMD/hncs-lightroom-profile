#!/usr/bin/env python3
"""Passe 2 : échantillons des 148 3FR (XCD 55V, 35-100E, 38V ; ISO 50 à 25600) contre l'export Phocus SDR.

Même idée que `echantillons.py` (qu'on importe, rien n'y est modifié) mais SANS JPEG du boîtier : la référence est
l'export Phocus seul (TIFF 16 bits Adobe RGB, C/phocus-sortie-2/B_XXXX.tif).  Pour chaque image, blocs uniformes de
16x16 px (pleine taille) avec

  cam_rgb     RGB caméra linéaire brut (rawpy, noir soustrait, demi-taille, sans matrice ni balance), moyenne du bloc
  phocus_xyz  export Phocus -> XYZ D50 linéaire
  wb_as_shot  multiplicateurs de balance du boîtier (R, G, B, G2)

Alignement RAW / Phocus : corrélation de la luminance (log) sur le centre (la géométrie Phocus peut être recadrée :
carrés de 8584 px, 3:2 de 7772 px).  Sélection : écart-type relatif < 0,04 sur RAW et Phocus (blocs de 8x8
demi-pixels), RAW et Phocus non écrêtés, et une couronne centrale plus étroite qu'en passe 1 (r^2 < 0,05 au lieu de
0,16) : Phocus applique ses corrections d'objectif (vignetage, distorsion) et Camera Raw ne les applique pas ici, elles
pèsent surtout vers les bords.  Les scènes de feuillage n'ont presque aucun bloc uniforme : échelle de relâchement
(ECHELLE : texture puis couronne) jusqu'à 1500 blocs ; le CV de chaque bloc est gardé pour pondérer l'ajustement.

  echantillons_passe2.py extraire [--seulement B0000001 ...] [--refaire] [--workers 4]
  echantillons_passe2.py fusionner       # data/samples-pass2.npz (< 40 Mo)
  echantillons_passe2.py --self-test
"""
import os

for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '2')

import argparse
import csv
import glob
import pathlib
import subprocess
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings('ignore')
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import echantillons as E  # noqa: E402

PROJET = E.PROJET
C = E.C
ENTREE2 = C / 'phocus-entree-2'
SORTIE2 = C / 'phocus-sortie-2'
OUT2 = C / 'echantillons-2'
TSV = PROJET / 'measurements' / 'selection-passe2.tsv'
NPZ2 = PROJET / 'data' / 'samples-pass2.npz'
RAYON2 = 0.05
ECHELLE = [(0.05, 0.04), (0.05, 0.06), (0.08, 0.06), (0.08, 0.08), (0.12, 0.08)]
TOL_VOISINS = 0.15   # écart relatif maximal de la luminance d'un bloc à la moyenne de son voisinage 3x3 (RAW et Phocus)
N_MIN = 1500
NOMINAUX = [(48, 64), (64, 2)]
PAR_IMAGE = E.PAR_IMAGE_FUSION


def meta_selection():
    """nom (B0000001) -> dict(objectif, focale, iso, comp, temp_K, be) depuis selection-passe2.tsv."""
    out = {}
    if not TSV.exists():
        # published data: the same fields are stored per image in data/samples-pass2.npz
        z = np.load(NPZ2)
        for i, n in enumerate(z['noms']):
            out[str(n)] = dict(objectif=str(z['objectif'][i]), focale=float(z['focale'][i]), iso=int(z['iso'][i]), comp=float(z['comp'][i]),
                               temp_K=float(z['temp_K'][i]), be=float(z['baseline_exposure'][i]))
        return out
    for r in csv.DictReader(open(TSV), delimiter='\t'):
        obj, _, foc = r['objectif'].partition('@')
        out[r['nom'][:8]] = dict(objectif=obj, focale=float(foc or 0), iso=int(r['ISO']), comp=float(r['compensation_EV']),
                                 temp_K=float(r['temperature_estimee_K']), be=float(r['BaselineExposure']))
    return out


def phocus_demi(mm, h, w):
    """Export Phocus (H,W,3 uint16 big-endian) -> float32 [0,1] demi-taille (H//2, W//2, 3), par tranches."""
    f = E.chunk_tiff(mm)
    out = np.empty((h // 2, (w - (w % 2)) // 2, 3), np.float32)
    for r0 in range(0, h // 2, 128):
        r1 = min(h // 2, r0 + 128)
        out[r0:r1] = f(r0, r1)
    return out


def extraire_image(nom, refaire=False):
    import rawpy
    out = OUT2 / f'{nom}.npz'
    if out.exists() and not refaire:
        return None
    tif = SORTIE2 / f'B_{nom[-4:]}.tif'
    raw_p = ENTREE2 / f'{nom}.3FR'
    anomalies = []
    d = E.lire_tiff(tif)
    g = E.icc_gamma_u8f8(d['icc'])
    assert g is not None and abs(g - E.GAMMA_ADOBE) < 1e-6, f'gamma ICC Phocus {g} != 563/256'
    assert np.abs(E.icc_colorants(d['icc']) - E.M_ADOBE).max() < 2e-3, 'colorants Adobe RGB inattendus'
    mm = np.memmap(tif, dtype='>u2', mode='r', offset=d['offset'], shape=(d['h'], d['w'], 3))
    nby, nbx = d['h'] // E.BLOC, d['w'] // E.BLOC
    ph = phocus_demi(mm, d['h'], d['w'])
    del mm
    lum_ph = np.log(np.clip(ph, 0, 1)[..., 1] ** E.GAMMA_ADOBE * E.M_ADOBE[1, 1] +
                    (np.clip(ph, 0, 1)[..., 0] ** E.GAMMA_ADOBE) * E.M_ADOBE[1, 0] +
                    (np.clip(ph, 0, 1)[..., 2] ** E.GAMMA_ADOBE) * E.M_ADOBE[1, 2] + 1e-3).astype(np.float32)

    r = rawpy.imread(str(raw_p))
    wb = np.array(r.camera_whitebalance, np.float32)
    raw = r.postprocess(half_size=True, output_color=rawpy.ColorSpace.raw, gamma=(1, 1), no_auto_bright=True,
                        user_wb=[1, 1, 1, 1], output_bps=16)
    flip_raw = int(r.sizes.flip)
    r.close()
    paysage = lambda s: s[1] >= s[0]
    cands = [k for k in range(4) if paysage(np.rot90(raw[..., 1], k).shape) == paysage(lum_ph.shape)]
    meilleur = (-1.0, None, 0)
    for k in cands:
        rg = np.log(np.rot90(raw[..., 1], k).astype(np.float32) / 65535 + 1e-3)
        o, c = aligner_ok(rg, lum_ph)
        if o is not None and c > meilleur[0]:
            meilleur = (c, o, k)
        if meilleur[0] > 0.9:
            break
    corr, off, k = meilleur
    if (off is None or corr < 0.6) and paysage(raw.shape) == paysage(lum_ph.shape):
        # repli : fort recalage de distorsion (35-100E au grand-angle) -> petit template central, accepté seulement
        # s'il reste près d'un décalage nominal (recadrage centré de Phocus : (48, 64) paysage, (64, 2) portrait)
        o2, c2 = E.aligner(np.log(raw[..., 1].astype(np.float32) / 65535 + 1e-3), lum_ph, T=300)
        if o2 is not None and c2 >= 0.55 and any(abs(o2[0] - a) <= 4 and abs(o2[1] - b) <= 4 for a, b in NOMINAUX):
            corr, off, k = c2, o2, 0
            anomalies.append('repli : petit template central')
    if off is None or corr < 0.6:
        raise RuntimeError(f'recalage RAW/Phocus douteux ({corr:.2f})')
    if k:
        raw = np.rot90(raw, k).copy()
        anomalies.append(f'RAW tourné de {k} quart(s)')
    dy, dx = off
    if dy < 0 or dx < 0 or dy + nby * E.BH > raw.shape[0] or dx + nbx * E.BH > raw.shape[1]:
        raise RuntimeError(f'décalage {off} hors du RAW {raw.shape}')
    if d['orientation'] != 1:
        anomalies.append(f'orientation TIFF {d["orientation"]}')

    m_raw, cv_raw, mx_raw = E.stats_blocs(E.chunk_array(raw, 65535.0, dy, dx), nby, nbx)
    m_pho, cv_pho, mx_pho = E.stats_blocs(E.chunk_array(ph, 1.0), nby, nbx)
    del raw, ph

    yy, xx = np.mgrid[0:nby, 0:nbx]
    rad2 = ((yy - nby / 2) / nby) ** 2 + ((xx - nbx / 2) / nbx) ** 2
    base = (mx_raw <= 0.98) & (m_pho.max(-1) < 0.985) & (m_raw[..., 1] > 1e-4)
    cvm = np.maximum(cv_raw, cv_pho)
    # échelle de relâchement : les scènes de feuillage n'ont presque aucun bloc uniforme ; on relâche d'abord le
    # critère de texture à couronne étroite, puis on élargit la couronne, jusqu'à N_MIN blocs
    from scipy import ndimage
    lr, lp = m_raw[..., 1].astype(np.float64), m_pho[..., 1].astype(np.float64)
    voisin_ok = (np.abs(lr / np.maximum(ndimage.uniform_filter(lr, 3, mode='nearest'), 1e-6) - 1) < TOL_VOISINS) & \
                (np.abs(lp / np.maximum(ndimage.uniform_filter(lp, 3, mode='nearest'), 1e-6) - 1) < TOL_VOISINS)
    for etage, (r2, th) in enumerate(ECHELLE):
        uni = base & (cvm < th)
        # le voisinage 3x3 doit être uniforme aussi (la distorsion corrigée par Phocus décale localement l'alignement,
        # jusqu'à un bloc en bordure de couronne au grand-angle) et de moyenne proche
        ero = ndimage.minimum_filter(uni.astype(np.uint8), size=3, mode='constant') > 0
        ok = ero & voisin_ok & (rad2 < r2)
        if ok.sum() >= N_MIN:
            break
    anomalies.append(f'étage {etage} (r2<{r2}, cv<{th}) : {int(ok.sum())} blocs')
    res = {'nom': nom, 'cam_rgb': m_raw[ok], 'wb_as_shot': wb,
           'phocus_xyz': E.decode_adobe(m_pho[ok].astype(np.float64)).astype(np.float32),
           'by': yy[ok].astype(np.int16), 'bx': xx[ok].astype(np.int16), 'grille': np.array([nby, nbx]),
           'decalage_raw': np.array([dy, dx]), 'corr_raw_phocus': corr, 'rot_raw': k, 'flip_libraw': flip_raw,
           'cv_raw': cv_raw[ok].astype(np.float16), 'cv_phocus': cv_pho[ok].astype(np.float16), 'etage': etage,
           'rad2': rad2[ok].astype(np.float16),
           'anomalies': np.array(anomalies, dtype=str)}
    OUT2.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, **res)
    return res


def aligner_ok(rg, lum_ph):
    """E.aligner avec un template de 600 demi-pixels : Phocus corrige la distorsion de l'objectif (échelle de ~0,3 % entre
    centre et bords), un grand template décorrèle (0,84 contre 0,98) alors que le décalage reste constant."""
    return E.aligner(rg, lum_ph, T=600)


def _travail(a):
    nom, refaire = a
    os.nice(10)
    t = time.time()
    try:
        r = extraire_image(nom, refaire)
    except Exception as e:   # une image en échec ne bloque pas le lot
        return f'{nom} ÉCHEC {e!r}'
    if r is None:
        return f'{nom} déjà fait'
    return (f'{nom} : {len(r["cam_rgb"])} blocs, corr {r["corr_raw_phocus"]:.3f}, décalage {tuple(int(x) for x in r["decalage_raw"])}, '
            f'{time.time() - t:.0f}s {list(r["anomalies"]) or ""}')


def fusionner():
    meta = meta_selection()
    fs = sorted(glob.glob(str(OUT2 / 'B*.npz')))
    if not fs:
        print('aucun échantillon à fusionner')
        return
    champs = ['cam_rgb', 'phocus_xyz', 'by', 'bx', 'cv_raw', 'cv_phocus', 'rad2']
    acc = {k: [] for k in champs}
    img, noms, wbs, tot, etages = [], [], [], [], []
    for i, f in enumerate(fs):
        d = np.load(f)
        s = E.sous_echantillon(d, PAR_IMAGE)
        for k in champs:
            acc[k].append(d[k][s].astype(np.float16) if k in ('cv_raw', 'cv_phocus', 'rad2') else d[k][s])
        img.append(np.full(len(s), i, np.int16))
        noms.append(str(d['nom'])); wbs.append(d['wb_as_shot']); tot.append(len(d['cam_rgb'])); etages.append(int(d['etage']))
    m = [meta[n] for n in noms]
    np.savez_compressed(
        NPZ2, **{k: np.concatenate(v) for k, v in acc.items()}, image=np.concatenate(img), noms=np.array(noms),
        wb_as_shot=np.array(wbs), blocs_par_image_total=np.array(tot), etage=np.array(etages),
        objectif=np.array([x['objectif'] for x in m]), focale=np.array([x['focale'] for x in m]),
        iso=np.array([x['iso'] for x in m]), comp=np.array([x['comp'] for x in m]),
        temp_K=np.array([x['temp_K'] for x in m]), baseline_exposure=np.array([x['be'] for x in m]),
        note=np.array('Passe 2, référence Phocus seule. cam_rgb : RGB caméra linéaire brut (noir soustrait, blanc de '
                      'saturation = 1, sans matrice ni balance) ; phocus_xyz : XYZ D50 linéaire ; by, bx : bloc (16 px) ; '
                      f'image : indice dans noms ; au plus {PAR_IMAGE} blocs par image ; couronne centrale r^2 < {RAYON2}'))
    n = sum(len(a) for a in acc['cam_rgb'])
    print(f'fusionné : {n} blocs sur {len(fs)} images -> {NPZ2} ({NPZ2.stat().st_size / 1e6:.1f} Mo)')


def self_test():
    import cv2
    # 1) metadonnées : le TSV se lit, 148 images, champs numériques
    m = meta_selection()
    assert len(m) >= 146 and all(v['iso'] > 0 and v['focale'] >= 0 for v in m.values())
    # 2) phocus_demi sur un TIFF synthétique en mémoire : moyenne 2x2 conforme
    h, w = 16, 24
    a = (np.arange(h * w * 3).reshape(h, w, 3) % 60000).astype('>u2')
    ph = phocus_demi(a, h, w)
    att = a.astype(np.float32).reshape(h // 2, 2, w // 2, 2, 3).mean((1, 3)) / 65535
    assert ph.shape == (h // 2, w // 2, 3) and np.abs(ph - att).max() < 1e-5
    # 3) alignement raw/Phocus recadré et décalé (réutilise E.aligner)
    rng = np.random.default_rng(2)
    tex = cv2.GaussianBlur(rng.random((900, 1100)).astype(np.float32), (0, 0), 3)
    sub = tex[100 + 5:100 + 5 + 600, 150 + 3:150 + 3 + 800]
    off, corr = aligner_ok(tex, sub)
    assert off == (105, 153) and corr > 0.99, (off, corr)
    # 4) l'ancien self-test d'echantillons.py passe toujours
    E.self_test()
    print('self-test OK (passe 2)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', nargs='?', choices=['extraire', 'fusionner'])
    ap.add_argument('--seulement', nargs='*')
    ap.add_argument('--refaire', action='store_true')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.action == 'extraire':
        from multiprocessing import Pool
        noms = a.seulement or sorted(meta_selection())
        with Pool(a.workers) as p:
            for ligne in p.imap_unordered(_travail, [(n, a.refaire) for n in noms]):
                print(ligne, flush=True)
        fusionner()
    elif a.action == 'fusionner':
        fusionner()


if __name__ == '__main__':
    sys.exit(main())
