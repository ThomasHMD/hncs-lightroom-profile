#!/usr/bin/env python3
"""Profil HNCS par dcamprof (chemin n° 2 de la SPEC) : un .dcp depuis samples-pass1.npz.

    python3 via_dcamprof.py                 # refait tout (courbe, gains, target, profils, mesure, rapport)
    python3 via_dcamprof.py --variante standard|neutral   # une seule variante
    python3 via_dcamprof.py --self-test     # le target écrit se relit, dcamprof répond (code 0 si tout passe)

dcamprof n'a pas de mode « imiter le JPEG d'un boîtier » (cherché dans sa doc : rien). Ses briques : un profil
colorimétrique natif (matrice + LUT) construit depuis un .ti3 (RVB caméra / XYZ de référence), puis, à
`make-dcp`, une courbe de tons (`-t`) et un opérateur de reproduction des tons (`-o` : `neutral` ajoute une
LookTable, `standard` met seulement la courbe dans le DCP). La référence (Phocus) est une image RENDUE : on
en retire donc la courbe avant d'ajuster.

  1. courbe : Y Phocus en fonction de Y scène (RVB caméra équilibré par wb_as_shot x ForwardMatrix Adobe) sur
     les blocs presque neutres, courbe monotone et gain par image alternés (médiane des gains = 0 IL), images
     d'ajustement seulement (indice % 4 != 3) ;
  2. référence « dé-courbée » : variante `standard` = inverse exact de l'opérateur RVB de la spec DNG
     (RefBaselineRGBTone : max et min par la courbe inverse, milieu interpolé) dans ProPhoto linéaire ;
     variante `neutral` = inverse en luminance seule (même chromaticité) ; RVB caméra x gain de l'image ;
  3. target .ti3 agrégé (médianes par case chromaticité x luminance) + patch blanc synthétique ;
  4. `make-profile`, puis `make-dcp -m <Adobe.dcp> -t courbe.json -o standard|neutral` ;
  5. mesure : les échantillons traversent le .dcp par `test-profile` en mode TIFF (chemin DNG de dcamprof,
     courbe et LookTable comprises), gain libre par image (à la prévision, côté caméra) contre Phocus puis
     contre le JPEG ; images tenues à part (indice % 4 == 3) jamais utilisées à l'ajustement.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import warnings

import numpy as np

warnings.filterwarnings('ignore')

PROJET = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
C = pathlib.Path(os.environ.get('HNCS_WORKDIR', 'workdir')).resolve()   # work folder (HNCS_WORKDIR)
DCAMPROF = pathlib.Path(os.environ.get('HNCS_DCAMPROF', 'dcamprof'))   # dcamprof 1.0.6 binary (HNCS_DCAMPROF)
TMP = C / 'tmp-dcamprof'
NPZ = PROJET / 'data/samples-pass1.npz'
ADOBE = pathlib.Path('/Library/Application Support/Adobe/CameraRaw/CameraProfiles/Adobe Standard/'
                     'Hasselblad 100-22-Coated6 Adobe Standard.dcp')
SORTIE_DCP = PROJET / 'profiles/HNCS-dcamprof.dcp'
RAPPORT = PROJET / 'measurements/dcamprof.md'
MODELE = 'Hasselblad 100-22-Coated6'
NOM_PROFIL = 'HNCS (dcamprof)'
D50 = np.array([0.9642, 1.0, 0.8249])
# ProPhoto RGB (D50) -> XYZ, comme data-examples/nil-profile.json de dcamprof
PP2XYZ = np.array([[0.7976749, 0.1351917, 0.0313534],
                   [0.2880402, 0.7118741, 0.0000857],
                   [0.0000000, 0.0000000, 0.8252100]])
XYZ2PP = np.linalg.inv(PP2XYZ)
GAMMA_PP = 461.0 / 256.0
NICE = ['nice', '-n', '10']


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- données

def charger():
    z = np.load(NPZ, allow_pickle=True)
    img = z['image'].astype(int)
    cam = z['cam_rgb'].astype(float)
    wb = z['wb_as_shot'].astype(float)[img][:, :3]
    d = dict(img=img, bal=cam * wb, raw=cam, phocus=z['phocus_xyz'].astype(float),
             jpeg=z['jpeg_xyz'].astype(float), noms=[str(n) for n in z['noms']])
    d['tenue'] = (img % 4) == 3
    return d


def lab(xyz):
    t = xyz / D50
    f = np.where(t > 216 / 24389, np.cbrt(t), (24389 / 27 * t + 16) / 116)
    return np.c_[116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])]


def de2000(xyz_a, xyz_b):
    import colour
    return colour.difference.delta_E_CIE2000(lab(np.asarray(xyz_a)), lab(np.asarray(xyz_b)))


def adobe_fm():
    import dcp_ecrire
    p = dcp_ecrire.lire(str(ADOBE))
    return np.array(p['ForwardMatrix1']).reshape(3, 3), np.array(p['ForwardMatrix2']).reshape(3, 3)


# --------------------------------------------------------------------------- courbe de tons et gains

def _courbe_depuis_points(x, y, n=4097):
    """Courbe monotone lissée, définie sur [0,1] en n points (gamma 2,2 : plus dense dans les ombres)."""
    from scipy.interpolate import PchipInterpolator
    xs = np.linspace(0, 1, n) ** 2.2
    f = PchipInterpolator(x, y, extrapolate=True)
    ys = np.clip(f(xs), 0, 1)
    ys = np.maximum.accumulate(ys)
    ys[0], ys[-1] = 0.0, 1.0
    return xs, ys


class Courbe:
    """Courbe de tons T (entrée scène linéaire -> sortie linéaire), table dense, avec inverse."""

    def __init__(self, xs, ys):
        self.xs, self.ys = np.asarray(xs), np.asarray(ys)
        # inverse : table strictement croissante en y
        yy = self.ys + np.arange(len(self.ys)) * 1e-12
        self.yy = yy

    def __call__(self, x):
        return np.interp(np.clip(x, 0, 1), self.xs, self.ys)

    def inverse(self, y):
        return np.interp(np.clip(y, 0, 1), self.yy, self.xs)


def ajuster_courbe(d, fit, fm_y, iterations=8):
    """Courbe + gain par image alternés sur les blocs presque neutres des images d'ajustement."""
    from scipy.optimize import minimize_scalar
    img, bal, ref = d['img'], d['bal'], d['phocus']
    L = lab(ref)
    chroma = np.hypot(L[:, 1], L[:, 2])
    ys = bal @ fm_y
    sel_n = fit & (chroma < 6) & (d['raw'].max(1) < 0.9) & (ys > 0.004)
    sel_m = fit & (ref[:, 1] > 0.05) & (ref[:, 1] < 0.6) & (d['raw'].max(1) < 0.9)
    nimg = len(d['noms'])
    g = np.ones(nimg)
    # noeuds : abscisses en puissance 1/2,2 de l'entrée
    kn = np.linspace(0.04, 1.0, 40) ** 2.2 * 0.9
    courbe = None
    for it in range(iterations):
        x = ys[sel_n] * g[img[sel_n]]
        y = ref[sel_n, 1]
        # médiane par case (cases en puissance) puis monotone
        bords = np.concatenate([[0], np.linspace(0.02, 1.0, 48) ** 2.2 * 0.95])
        px, py = [0.0], [0.0]
        for a, b in zip(bords[:-1], bords[1:]):
            m = (x >= a) & (x < b)
            if m.sum() >= 40 and np.median(x[m]) < 0.78:
                px.append(np.median(x[m]))
                py.append(np.median(y[m]))
        px, py = np.array(px), np.array(py)
        py = np.maximum.accumulate(py)
        # épaule : on joint (1,1)
        px = np.append(px, 1.0)
        py = np.append(py, 1.0)
        # PCHIP exige x strictement croissant
        keep = np.concatenate([[True], np.diff(px) > 1e-6])
        px, py = px[keep], py[keep]
        xs, ys_c = _courbe_depuis_points(px, py)
        courbe = Courbe(xs, ys_c)
        # gains : minimise l'écart en log sur les tons moyens (toutes couleurs), par image
        gnew = g.copy()
        for i in range(nimg):
            m = sel_m & (img == i)
            if m.sum() < 20:
                continue
            xi, yi = ys[m], ref[m, 1]
            fun = lambda lg: np.mean(np.abs(np.log(np.maximum(courbe(xi * 2 ** lg), 1e-6)) - np.log(yi)))
            r = minimize_scalar(fun, bounds=(-2.5, 2.5), method='bounded', options={'xatol': 1e-3})
            gnew[i] = 2 ** r.x
        # médiane des gains (images d'ajustement) = 0 IL
        fit_imgs = sorted(set(img[fit]))
        gnew = gnew / np.exp(np.median(np.log(gnew[fit_imgs])))
        dg = np.max(np.abs(np.log2(gnew[fit_imgs] / g[fit_imgs])))
        g = gnew
        log(f'  courbe/gains iter {it}: ecart max des gains {dg:.4f} IL, {sel_n.sum()} blocs neutres')
        if dg < 0.003:
            break
    return courbe, g


def ecrire_courbe_json(courbe, chemin):
    """Courbe au format `Linear` de dcamprof (centaines de poignées), abscisses gamma 2,2 des deux côtés."""
    n = 1025
    u = np.linspace(0, 1, n)
    x = u ** 2.2
    y = courbe(x)
    h = [[float(a), float(b ** (1 / 2.2))] for a, b in zip(u, y)]
    h[0], h[-1] = [0.0, 0.0], [1.0, 1.0]
    json.dump({'CurveType': 'Linear', 'CurveHandles': h, 'CurveGamma': 2.2}, open(chemin, 'w'))


# --------------------------------------------------------------------------- référence dé-courbée

def tone_rgb(p, courbe):
    """Opérateur RVB de la spec DNG (RefBaselineRGBTone) sur ProPhoto linéaire (N,3) : max et min par la courbe,
    milieu interpolé."""
    p = np.asarray(p, float)
    o = np.argsort(p, axis=1)
    s = np.take_along_axis(p, o, 1)
    lo, mi, hi = s[:, 0], s[:, 1], s[:, 2]
    tlo, thi = courbe(lo), courbe(hi)
    den = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    tmi = np.where(hi - lo > 1e-12, tlo + (thi - tlo) * (mi - lo) / den, tlo)
    out = np.empty_like(p)
    np.put_along_axis(out, o, np.c_[tlo, tmi, thi], 1)
    return out


def tone_rgb_inverse(q, courbe):
    q = np.asarray(q, float)
    o = np.argsort(q, axis=1)
    s = np.take_along_axis(q, o, 1)
    lo, mi, hi = s[:, 0], s[:, 1], s[:, 2]
    ilo, ihi = courbe.inverse(lo), courbe.inverse(hi)
    den = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    imi = np.where(hi - lo > 1e-12, ilo + (ihi - ilo) * (mi - lo) / den, ilo)
    out = np.empty_like(q)
    np.put_along_axis(out, o, np.c_[ilo, imi, ihi], 1)
    return out


def decourber(xyz, courbe, variante):
    """XYZ D50 rendu -> XYZ D50 « scène » (avant courbe)."""
    xyz = np.asarray(xyz, float)
    if variante == 'standard':
        pp = np.clip(xyz @ XYZ2PP.T, 0, None)
        return tone_rgb_inverse(pp, courbe) @ PP2XYZ.T
    y = np.maximum(xyz[:, 1], 1e-9)
    return xyz * (courbe.inverse(y) / y)[:, None]


# --------------------------------------------------------------------------- target .ti3

def agreger(rgb, xyz, nchroma=0.012, nlum=14):
    """Médianes par case u'v' x log Y : renvoie (rgb, xyz) agrégés."""
    X, Y, Z = xyz.T
    den = np.maximum(X + 15 * Y + 3 * Z, 1e-9)
    u, v = 4 * X / den, 9 * Y / den
    ly = np.log2(np.maximum(Y, 1e-6))
    cases = np.c_[np.floor(u / nchroma), np.floor(v / nchroma), np.floor(ly * nlum / 14 * 1.0)].astype(np.int64)
    _, inv = np.unique(cases, axis=0, return_inverse=True)
    inv = inv.ravel()
    n = inv.max() + 1
    out_r, out_x, cnt = np.zeros((n, 3)), np.zeros((n, 3)), np.bincount(inv, minlength=n)
    order = np.argsort(inv, kind='stable')
    bornes = np.concatenate([[0], np.cumsum(cnt)])
    for k in range(n):
        idx = order[bornes[k]:bornes[k + 1]]
        out_r[k] = np.median(rgb[idx], axis=0)
        out_x[k] = np.median(xyz[idx], axis=0)
    return out_r, out_x, cnt


def ecrire_ti3(chemin, rgb, xyz, classes=None):
    """Argyll .ti3 minimal (sans spectres) : RVB et XYZ en pourcents (convention des .ti3 de dcamprof)."""
    n = len(rgb)
    l = ['CTI3', '', 'DESCRIPTOR "Argyll Calibration Target chart information 3"', 'ORIGINATOR "via_dcamprof.py"',
         'KEYWORD "DEVICE_CLASS"', 'DEVICE_CLASS "INPUT"', 'KEYWORD "COLOR_REP"', 'COLOR_REP "RGB_XYZ"', '',
         'NUMBER_OF_FIELDS 9', 'BEGIN_DATA_FORMAT',
         'SAMPLE_ID SAMPLE_CLASS SAMPLE_TYPE RGB_R RGB_G RGB_B XYZ_X XYZ_Y XYZ_Z', 'END_DATA_FORMAT', '',
         f'NUMBER_OF_SETS {n}', 'BEGIN_DATA']
    for i in range(n):
        c = classes[i] if classes is not None else 'hncs'
        l.append(f'{"WHITE" if c == "white" else f"P{i + 1:05d}"} "{c}" "R" ' + ' '.join(f'{v * 100:.6f}' for v in rgb[i]) + ' '
                 + ' '.join(f'{v * 100:.6f}' for v in xyz[i]))
    l.append('END_DATA')
    pathlib.Path(chemin).write_text('\n'.join(l) + '\n')


def lire_ti3(chemin):
    """Relit les lignes de données : (ids, rgb, xyz) en unités 0..1."""
    txt = pathlib.Path(chemin).read_text().splitlines()
    i = txt.index('BEGIN_DATA')
    j = txt.index('END_DATA')
    ids, rgb, xyz = [], [], []
    for ln in txt[i + 1:j]:
        t = re.findall(r'"[^"]*"|\S+', ln)
        ids.append(t[0])
        v = [float(a) / 100 for a in t[3:9]]
        rgb.append(v[:3])
        xyz.append(v[3:])
    return ids, np.array(rgb), np.array(xyz)


def construire_target(d, fit, courbe, gains, variante, chemin, nchroma=0.012, blanc='synthetique', mincnt=3):
    """target .ti3 : RVB caméra équilibré x gain de l'image, XYZ de référence dé-courbé (images d'ajustement).
    blanc : 'synthetique' (RVB 1,1,1 -> blanc D50), 'aucun'."""
    img = d['img']
    sel = fit & (d['raw'].max(1) < 0.9)
    rgb = d['bal'][sel] * gains[img[sel]][:, None]
    xyz = decourber(d['phocus'][sel], courbe, variante)
    ok = (xyz[:, 1] > 0.004) & (rgb.max(1) < 1.0)
    rgb, xyz = rgb[ok], xyz[ok]
    r, x, cnt = agreger(rgb, xyz, nchroma)
    keep = cnt >= mincnt
    r, x = r[keep], x[keep]
    cls = ['hncs'] * len(r)
    if blanc == 'synthetique':
        s = 0.9
        r = np.vstack([r, [[s, s, s]]])
        x = np.vstack([x, [D50 * s]])
        cls.append('white')
    ecrire_ti3(chemin, r, x, cls)
    return len(r)


def fabriquer(d, fit, courbe, gains, variante, tag, opts=None, dossier=None):
    """target -> profile.json -> .dcp ; renvoie le chemin du .dcp. opts : blanc, nchroma, mp (make-profile), md (make-dcp)."""
    opts = opts or {}
    dossier = pathlib.Path(dossier or TMP)
    ti3, pj, dcp = dossier / f't-{tag}.ti3', dossier / f'p-{tag}.json', dossier / f'd-{tag}.dcp'
    cj = dossier / 'courbe.json'
    ecrire_courbe_json(courbe, cj)
    n = construire_target(d, fit, courbe, gains, variante, ti3, opts.get('nchroma', 0.012),
                          opts.get('blanc', 'synthetique'), opts.get('mincnt', 3))
    mp = ['make-profile', '-i', 'D50', '-I', 'D50', '-n', MODELE] + list(opts.get('mp', []))
    if opts.get('blanc', 'synthetique') == 'synthetique':
        mp += ['-b', 'WHITE']
    out = dcamprof(mp + [ti3, pj])
    m = re.search(r'Native LUT patch match average DE ([\d.]+).*?median DE ([\d.]+)', out, re.S)
    md = ['make-dcp', '-n', MODELE, '-d', NOM_PROFIL, '-m', ADOBE, '-t', cj, '-o',
          opts.get('operateur', variante)] + list(opts.get('md', []))
    dcamprof(md + [pj, dcp])
    return dcp, n, (m.groups() if m else None)


# --------------------------------------------------------------------------- dcamprof : appels et rendu TIFF

def dcamprof(args, check=True, quiet=True):
    r = subprocess.run(NICE + [str(DCAMPROF)] + [str(a) for a in args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f'dcamprof {" ".join(map(str, args[:2]))} a échoué ({r.returncode}) :\n{r.stderr[-1500:]}')
    return r.stdout + r.stderr


def rendre(dcp, rgb, tmp=None, largeur=2048):
    """RVB caméra équilibré (N,3, linéaire, ~[0,1]) -> XYZ D50 rendu par le .dcp (chemin DNG de dcamprof :
    matrices, HueSatMap, LookTable, courbe). Les valeurs > 1 sont écrêtées (limite du TIFF 16 bits)."""
    import cv2
    tmp = pathlib.Path(tmp or TMP)
    n = len(rgb)
    h = -(-n // largeur)
    buf = np.zeros((h * largeur, 3))
    buf[:n] = np.clip(rgb, 0, 1)
    enc = np.round((buf ** (1 / GAMMA_PP)) * 65535).astype(np.uint16).reshape(h, largeur, 3)
    entree, sortie = tmp / 'rend-in.tif', tmp / 'rend-out.tif'
    cv2.imwrite(str(entree), enc[:, :, ::-1])
    dcamprof(['test-profile', '-w', 'm1,1,1', entree, dcp, sortie])
    out = cv2.imread(str(sortie), cv2.IMREAD_UNCHANGED)
    if out is None or out.dtype != np.uint16:
        raise RuntimeError('lecture du TIFF de sortie impossible')
    lin = (out[:, :, ::-1].reshape(-1, 3)[:n] / 65535.0) ** GAMMA_PP
    return lin @ PP2XYZ.T


# --------------------------------------------------------------------------- mesure : gain libre par image

def gains_depart(d, courbe, fm_y):
    """Gain de départ par image (tons moyens, toutes couleurs), pour toutes les images y compris tenues à part."""
    from scipy.optimize import minimize_scalar
    img, ref = d['img'], d['phocus']
    ys = d['bal'] @ fm_y
    g = np.ones(len(d['noms']))
    for i in range(len(g)):
        m = (img == i) & (ref[:, 1] > 0.05) & (ref[:, 1] < 0.6) & (d['raw'].max(1) < 0.9)
        if m.sum() < 20:
            continue
        xi, yi = ys[m], ref[m, 1]
        fun = lambda lg: np.mean(np.abs(np.log(np.maximum(courbe(xi * 2 ** lg), 1e-6)) - np.log(yi)))
        g[i] = 2 ** minimize_scalar(fun, bounds=(-2.5, 2.5), method='bounded', options={'xatol': 1e-3}).x
    return g


def _scan(dcp, d, idx_par_image, g0, offsets, ref, tmp):
    """Pour chaque image : médiane de ΔE2000 à chaque décalage de gain (en IL) autour de g0. Un seul TIFF."""
    morceaux, meta = [], []
    for i, idx in enumerate(idx_par_image):
        if len(idx) == 0:
            continue
        for o in offsets[i]:
            morceaux.append(d['bal'][idx] * (g0[i] * 2 ** o))
            meta.append((i, o, len(idx)))
    rgb = np.vstack(morceaux)
    xyz = rendre(dcp, rgb, tmp)
    de = de2000(xyz, np.vstack([ref[idx_par_image[i]] for i, o, n in meta]))
    res, p = {}, 0
    for i, o, n in meta:
        res.setdefault(i, []).append((o, float(np.median(de[p:p + n]))))
        p += n
    return res


def gains_libres(dcp, d, g0, ref, tmp=None, max_par_image=2500, graine=0):
    """Gain par image au meilleur ΔE2000 médian contre `ref` (grille grossière puis fine). Renvoie gains (x g0)."""
    rng = np.random.default_rng(graine)
    nimg = len(d['noms'])
    idx = []
    for i in range(nimg):
        ii = np.where((d['img'] == i) & (d['raw'].max(1) < 0.9))[0]
        if len(ii) > max_par_image:
            ii = np.sort(rng.choice(ii, max_par_image, replace=False))
        idx.append(ii)
    grossier = {i: np.arange(-0.6, 0.601, 0.06) for i in range(nimg)}
    r1 = _scan(dcp, d, idx, g0, grossier, ref, tmp)
    best = {i: min(v, key=lambda t: t[1])[0] for i, v in r1.items()}
    fin = {i: best[i] + np.arange(-0.06, 0.0601, 0.01) for i in best}
    r2 = _scan(dcp, d, idx, g0, fin, ref, tmp)
    g = g0.copy()
    for i, v in r2.items():
        o = np.array([t[0] for t in v])
        m = np.array([t[1] for t in v])
        g[i] = g0[i] * 2 ** o[np.argmin(m)]
    return g


def mesurer(dcp, d, g0, tmp=None, gains=None):
    """ΔE2000 de tous les blocs contre Phocus puis le JPEG (gain libre propre à chaque référence), + gain fixe."""
    out = {}
    sel = d['raw'].max(1) < 0.9
    for nom in ('phocus', 'jpeg'):
        if gains is not None and nom in gains:
            g = gains[nom]
        else:
            g = gains_libres(dcp, d, g0, d[nom], tmp)
        rgb = d['bal'] * g[d['img']][:, None]
        xyz = rendre(dcp, rgb, tmp)
        de = de2000(xyz, d[nom])
        out[nom] = dict(gains=g, de=de)
    return out


def resumer(d, res):
    """Tableau (ajustement / tenues à part) x (Phocus / JPEG) : médiane, 90e centile, nombre de blocs."""
    sel = d['raw'].max(1) < 0.9
    lignes = {}
    for nom in ('phocus', 'jpeg'):
        de = res[nom]['de']
        for lib, m in (('ajustement', ~d['tenue'] & sel), ('tenues à part', d['tenue'] & sel)):
            lignes[(lib, nom)] = (float(np.median(de[m])), float(np.percentile(de[m], 90)), int(m.sum()))
    return lignes


# --------------------------------------------------------------------------- orchestration

CHROMA_SCALING = 1.0   # variante neutral : réglage de l'opérateur (auto = 1,118 sur cette courbe ; 1,0 mesuré meilleur)
D_LUT = 0.005          # make-profile -d : distance chromatique minimale entre patches dans le LUT (défaut 0,02)


def conf_neutral(chemin):
    src = (DCAMPROF.parent / 'data-examples/ntro_conf.json').read_text()
    out = re.sub(r'"ChromaScaling":\s*-1', f'"ChromaScaling": {CHROMA_SCALING}', src)
    assert out != src
    pathlib.Path(chemin).write_text(out)
    return str(chemin)


def options_variante(variante):
    o = dict(mp=['-d', str(D_LUT)])
    if variante == 'neutral':
        o['operateur'] = conf_neutral(TMP / 'ntro_conf.json')
    return o


def verifier_dcp(chemin):
    """Contrôles du .dcp : nom de modèle exact, ColorMatrix et illuminants d'Adobe, courbe et tables présentes."""
    import dcp_ecrire
    p, a = dcp_ecrire.lire(str(chemin)), dcp_ecrire.lire(str(ADOBE))
    err = []
    if p.get('UniqueCameraModel') != MODELE:
        err.append('UniqueCameraModel')
    for k in ('ColorMatrix1', 'ColorMatrix2', 'CalibrationIlluminant1', 'CalibrationIlluminant2'):
        if not np.allclose(p[k], a[k], atol=1e-4):
            err.append(k)
    if p.get('ProfileName') != NOM_PROFIL:
        err.append('ProfileName')
    for k in ('ForwardMatrix1', 'ForwardMatrix2', 'ProfileHueSatMapData1', 'ProfileHueSatMapData2', 'ProfileToneCurve'):
        if k not in p:
            err.append('absent: ' + k)
    return p, err


def fmt(x):
    return f'{x:.2f}'.replace('.', ',')


def ecrire_rapport(infos, d, courbe, gains, resultats, choisi, nb_patches, fixe):
    L = ['# Profil HNCS par dcamprof (chemin n° 2)', '',
         f'Produit par `tools/via_dcamprof.py` (dcamprof 1.0.6). {len(d["noms"])} images, '
         f'{int((~d["tenue"]).sum())} blocs d\'ajustement (images d\'indice % 4 != 3), '
         f'{int(d["tenue"].sum())} blocs tenus à part (indice % 4 == 3, jamais utilisés pour la courbe, les gains ni le target).', '',
         '## Méthode', '',
         'dcamprof n\'a pas de mode « imiter le rendu d\'un boîtier » (rien dans sa doc ni dans le code ; il vise un profil '
         'colorimétrique, plus une courbe et un « look » facultatifs). Chemin retenu :', '',
         '1. Courbe de tons mesurée sur les blocs presque neutres (chroma Phocus < 6) : Y Phocus en fonction de Y scène '
         '(RVB caméra x `wb_as_shot`, ligne Y de la ForwardMatrix2 d\'Adobe) x gain de l\'image ; courbe monotone (PCHIP sur '
         'médianes par case) et gain par image alternés, médiane des gains = 0 IL, jointe à (1,1). Écrite au format `Linear` '
         'de dcamprof, 1025 poignées en gamma 2,2.',
         '2. Référence dé-courbée : variante `standard` = inverse exact de l\'opérateur RVB de la spec DNG dans ProPhoto linéaire ; '
         'variante `neutral` = inverse en luminance seule (chromaticité conservée). RVB caméra multiplié par le gain de l\'image.',
         f'3. Target .ti3 agrégé (médianes par case u\'v\' 0,012 x luminance, au moins 3 blocs) : {nb_patches} patches + un blanc '
         'synthétique (RVB 1,1,1 -> blanc D50, désigné par `-b WHITE`).',
         f'4. `dcamprof make-profile -i D50 -I D50 -n "{MODELE}" -d {D_LUT} -b WHITE target.ti3 profile.json` '
         '(`-d 0,005` au lieu de 0,02 : le LUT corrige alors les teintes presque neutres, gain d\'environ 0,5 ΔE).',
         f'5. `dcamprof make-dcp -n "{MODELE}" -d "{NOM_PROFIL}" -m <Adobe Standard.dcp> -t courbe.json -o <opérateur> profile.json out.dcp` '
         '(ColorMatrix1/2 et illuminants StdA/D65 d\'Adobe repris par `-m` ; dcamprof duplique la ForwardMatrix dans les '
         'deux illuminants, elle est faite sur RVB déjà équilibré).', '',
         f'Variante livrée : **{choisi}**'
         + (f' (opérateur `neutral` avec `ChromaScaling` {CHROMA_SCALING} au lieu des 1,118 automatiques : 1,3 et 1,5 étaient '
            'nettement pires, 0,85 meilleur contre le JPEG mais pire contre Phocus).' if choisi == 'neutral'
            else ' (opérateur `standard` : courbe seule, HueSatMap sans LookTable).'), '',
         '## Mesure', '',
         'Les 124 414 blocs (écrêtage brut > 0,9 exclu) traversent le .dcp par `dcamprof test-profile` en mode TIFF '
         '(chemin DNG de dcamprof : matrices, HueSatMap, LookTable, courbe). Chaque image reçoit un gain libre (en amont, côté '
         'caméra), choisi au meilleur ΔE2000 médian contre la référence considérée (Phocus d\'abord, puis JPEG), car HNCS règle '
         'la luminosité photo par photo. Pour les images tenues à part, seul ce gain est ajusté. ΔE2000 en Lab D50.', '']
    for v, res in resultats.items():
        r = resumer(d, res)
        L += [f'### Variante `{v}`' + (' (livrée)' if v == choisi else ''), '',
              '| blocs | contre Phocus : médiane | 90e | contre JPEG : médiane | 90e |', '|---|---|---|---|---|']
        for lib in ('ajustement', 'tenues à part'):
            a, b = r[(lib, 'phocus')], r[(lib, 'jpeg')]
            L.append(f'| {lib} ({a[2]}) | {fmt(a[0])} | {fmt(a[1])} | {fmt(b[0])} | {fmt(b[1])} |')
        f = fixe[v]
        L += [f'| sans gain par image, ajustement / tenues à part (0 IL) | {fmt(f[("ajustement", "phocus")][0])} / '
              f'{fmt(f[("tenues à part", "phocus")][0])} | {fmt(f[("ajustement", "phocus")][1])} / '
              f'{fmt(f[("tenues à part", "phocus")][1])} | {fmt(f[("ajustement", "jpeg")][0])} / '
              f'{fmt(f[("tenues à part", "jpeg")][0])} | {fmt(f[("ajustement", "jpeg")][1])} / '
              f'{fmt(f[("tenues à part", "jpeg")][1])} |', '']
    L += ['Repère : Phocus contre JPEG du boîtier, ΔE2000 médiane 1,97 brute et 1,25 après gain par image (`phocus-vs-jpeg.md`).', '']
    gl = np.log2(resultats[choisi]['phocus']['gains'] / gains)
    L += ['## Courbe de tons (entrée scène -> sortie)', '',
          '| entrée | ' + ' | '.join(f'{x:g}' for x in (0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0)) + ' |',
          '|---|' + '---|' * 9,
          '| sortie | ' + ' | '.join(fmt(float(courbe(x))) for x in (0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0)) + ' |', '',
          f'Gains par image estimés à l\'ajustement : de {fmt(np.log2(gains).min())} à {fmt(np.log2(gains).max())} IL '
          f'(médiane 0 par construction) ; ils reflètent la luminosité auto de HNCS (jusqu\'à +2 IL sur quelques images). '
          f'Gain libre final contre Phocus : écart médian {fmt(float(np.median(np.abs(gl))))} IL avec le gain d\'ajustement.', '',
          '## Limites', '',
          '- Un profil fixe ne rejoue pas la luminosité auto de HNCS : dans Lightroom il reste un réglage d\'exposition par photo '
          '(les ΔE ci-dessus supposent ce gain optimal). L\'exposition absolue de la courbe suppose que Lightroom présente au profil '
          'le RAW normalisé x balance sans BaselineExposure ; si Lightroom en ajoute un, la médiane des gains se décale d\'autant '
          '(tag `-b` de `make-dcp` ou curseur d\'exposition) : à vérifier au premier essai réel.',
          '- Neutres : Phocus rend les gris de la balance du boîtier avec une dominante chaude (b* d\'environ +2 à +3, a* d\'environ +0,5 '
          'à +1) ; un DCP ne peut pas teinter l\'axe neutre (ForwardMatrix = blanc D50 imposé, HueSatMap et LookTable sans effet à '
          'saturation 0). Reste de l\'écart sur plus d\'un tiers des blocs ; compensable par un décalage de balance des blancs.',
          '- HueSatMap 2,5D : pas de correction de clarté par teinte. dcamprof n\'ajuste pas de LookTable 3D sur un rendu ; '
          'la LookTable de la variante `neutral` vient de son opérateur, pas d\'un ajustement sur Phocus.',
          '- Hautes lumières : peu de blocs neutres au-dessus de 0,8 (épaule de la courbe interpolée jusqu\'à (1,1)) ; Phocus y '
          'comprime plus que la courbe seule.',
          '- Le ΔE est celui du modèle DNG de dcamprof (référence de la spec DNG), pas un rendu Lightroom réel ; BaselineExposure, '
          'courbe de Lightroom et traitement du noir peuvent différer. Valeurs RVB > 1 après gain écrêtées (TIFF 16 bits), '
          'rares.', '',
          '## Fichiers', '',
          '- `profiles/HNCS-dcamprof.dcp` : profil livré (`UniqueCameraModel` = « Hasselblad 100-22-Coated6 », `ProfileName` = « HNCS (dcamprof) »).',
          '- `profiles/HNCS-dcamprof-<autre variante>.dcp` : l\'autre variante, pour comparaison.',
          '- Refaire : `python3 tools/via_dcamprof.py` (temporaires dans `tmp-dcamprof/` du chantier).', '']
    RAPPORT.write_text('\n'.join(L))


def tout(variantes=('neutral', 'standard')):
    TMP.mkdir(parents=True, exist_ok=True)
    SORTIE_DCP.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    d = charger()
    fit = ~d['tenue']
    fm1, fm2 = adobe_fm()
    log('courbe de tons et gains (images d\'ajustement)...')
    courbe, gains = ajuster_courbe(d, fit, fm2[1], iterations=12)
    g0 = gains_depart(d, courbe, fm2[1])
    resultats, dcps, fixe, nb = {}, {}, {}, 0
    for v in variantes:
        log(f'variante {v} : target, make-profile, make-dcp...')
        dcp, n, m = fabriquer(d, fit, courbe, gains, v, v, options_variante(v))
        nb = n
        log(f'  {n} patches ; DE natif (moyen, médian) {m}')
        log('  mesure (gain libre par image)...')
        res = mesurer(dcp, d, g0)
        ones = np.ones(len(d['noms']))
        fixe[v] = resumer(d, mesurer(dcp, d, g0, gains={'phocus': ones, 'jpeg': ones}))
        resultats[v], dcps[v] = res, dcp
        r = resumer(d, res)
        log('  ' + ' ; '.join(f'{k[0]}/{k[1]} {x[0]:.2f}/{x[1]:.2f}' for k, x in r.items()))
    choisi = min(resultats, key=lambda v: resumer(d, resultats[v])[('ajustement', 'phocus')][0])
    import shutil
    for v, dcp in dcps.items():
        cible = SORTIE_DCP if v == choisi else SORTIE_DCP.with_name(f'HNCS-dcamprof-{v}.dcp')
        shutil.copyfile(dcp, cible)
        p, err = verifier_dcp(cible)
        log(f'{cible.name} : {"OK" if not err else "ERREURS " + str(err)}')
    ecrire_rapport({}, d, courbe, gains, resultats, choisi, nb, fixe)
    log(f'rapport {RAPPORT} ; {time.time() - t0:.0f} s')
    return 0


# --------------------------------------------------------------------------- self-test

def self_test():
    import shutil
    if not (shutil.which(DCAMPROF) or pathlib.Path(DCAMPROF).exists()):
        print('SELF-TEST IGNORE : dcamprof introuvable (HNCS_DCAMPROF), outil facultatif')
        return 0
    TMP.mkdir(parents=True, exist_ok=True)
    ok = True

    def verif(nom, cond, detail=''):
        nonlocal ok
        print(('OK   ' if cond else 'ECHEC'), nom, detail)
        ok &= bool(cond)

    rep = pathlib.Path(tempfile.mkdtemp(prefix='st-', dir=TMP))
    out = dcamprof(['-v'])
    verif('dcamprof répond', '1.0' in out, out.strip()[:40])
    rng = np.random.default_rng(1)
    rgb = rng.uniform(0.03, 0.9, (300, 3))
    fm = np.array([[0.72, 0.136, 0.109], [0.26, 0.712, 0.028], [0.0002, 0.004, 0.821]])
    xyz = (rgb @ fm.T) * (1 + 0.1 * np.sin(5 * rgb[:, ::-1]))
    rgb = np.vstack([rgb, [[0.9, 0.9, 0.9]]])
    xyz = np.vstack([xyz, D50 * 0.9])
    ti3 = rep / 'st.ti3'
    ecrire_ti3(ti3, rgb, xyz, ['hncs'] * 300 + ['white'])
    ids, r2, x2 = lire_ti3(ti3)
    verif('target écrit se relit', np.allclose(r2, rgb, atol=1e-6) and np.allclose(x2, xyz, atol=1e-6) and ids[-1] == 'WHITE')
    out = dcamprof(['make-target', '-X', '-R', '-p', ti3, rep / 'st2.ti3'])
    verif('dcamprof relit le .ti3', (rep / 'st2.ti3').exists(), '')
    x = np.linspace(0, 1, 2001) ** 2.2
    courbe = Courbe(x, np.clip(1 - (1 - x) ** 1.8, 0, 1))
    dcp, n, m = fabriquer_simple(courbe, ti3, rep)
    p, err = verifier_dcp(dcp)
    verif('make-profile + make-dcp + contrôles du .dcp', not err, str(err))
    rampe = np.linspace(0.05, 0.9, 8)[:, None] * np.ones((1, 3))
    y = rendre(dcp, rampe, rep)[:, 1]
    verif('rendu TIFF : gris = courbe', np.allclose(y, courbe(rampe[:, 0]), atol=0.01), f'écart {np.abs(y - courbe(rampe[:, 0])).max():.4f}')
    if SORTIE_DCP.exists():
        p, err = verifier_dcp(SORTIE_DCP)
        verif('profil livré conforme', not err, str(err))
    print('SELF-TEST', 'OK' if ok else 'ECHEC')
    return 0 if ok else 1


def fabriquer_simple(courbe, ti3, dossier):
    pj, dcp, cj = dossier / 'p.json', dossier / 'd.dcp', dossier / 'c.json'
    ecrire_courbe_json(courbe, cj)
    out = dcamprof(['make-profile', '-i', 'D50', '-I', 'D50', '-n', MODELE, '-b', 'WHITE', ti3, pj])
    dcamprof(['make-dcp', '-n', MODELE, '-d', NOM_PROFIL, '-m', ADOBE, '-t', cj, '-o', 'standard', pj, dcp])
    return dcp, None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--variante', choices=['neutral', 'standard'])
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    for _d in ("measurements", "profiles"):
        (PROJET / _d).mkdir(exist_ok=True)   # output folders, created on first real run
    sys.exit(tout((a.variante,) if a.variante else ('neutral', 'standard')))


if __name__ == '__main__':
    main()
