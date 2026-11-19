#!/usr/bin/env python3
"""Ajuste un profil DCP « HNCS » pour le Hasselblad X2D II dans la chaîne Adobe (chemin n°1 de la SPEC).

Ce qui est ajusté (tout le reste vient du DCP Adobe du boîtier, « Hasselblad 100-22-Coated6 ») :
  - ColorMatrix1/2 et illuminants d'Adobe, inchangés (la balance des blancs de Lightroom en dépend) ;
  - ForwardMatrix1/2 = M · FM Adobe, M = I + E·P (le blanc D50 reste fixe, donc le neutre reste neutre) ;
  - ProfileToneCurve : 15 nœuds monotones, spline d'Adobe (départ : courbe ACR3 par défaut) ;
  - ProfileLookTable 3D, 36 teintes x 8 saturations x 8 valeurs (encodage sRGB), lissée, tirée vers le
    neutre, saturation 0 strictement neutre ; pas de HueSatMap ;
  - un gain d'exposition libre PAR IMAGE (HNCS règle la luminosité photo par photo) : jamais dans le profil,
    sauf le résidu de sa médiane (BaselineExposureOffset) ; DefaultBlackRender = 1 (aucun noir automatique,
    la chaîne de rendu modélisée est celle sans noir).

Méthode : alternance (gain par image, courbe, FM) par moindres carrés robustes (Huber) sur ΔE2000, et
(LookTable) par régression linéaire creuse dans l'espace HSV de la chaîne, après inversion de la courbe sur
la cible Phocus.  Images d'indice = 3 mod 4 tenues à part (seul leur gain est ajusté).  Tous les chiffres du
rapport sont calculés avec `chaine_adobe.rendre_xyz_d50` sur le DCP relu.

    python3 ajuster.py                  # tout : ajustement, DCP, ajustement.md, figure, planche
    python3 ajuster.py --sans-planche   # sans la planche (décodage de 4 3FR)
    python3 ajuster.py --depuis-etat    # refait les livrables depuis tmp-ajuster/etat.npz
    python3 ajuster.py --self-test      # données synthétiques, code de sortie 0 si tout passe
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "6")

import argparse
import pathlib
import sys
import time
import warnings

import numpy as np
from scipy import sparse
from scipy.optimize import least_squares, minimize_scalar
from scipy.sparse.linalg import spsolve

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chaine_adobe as ca  # noqa: E402
import dcp_ecrire  # noqa: E402

PROJET = pathlib.Path(__file__).resolve().parent.parent
C = pathlib.Path(os.environ.get('HNCS_WORKDIR', 'workdir')).resolve()   # work folder (HNCS_WORKDIR)
TMP = C / "tmp-ajuster"
NPZ = PROJET / "data" / "samples-pass1.npz"
DCP_SORTIE = PROJET / "profiles" / "Hasselblad X2D II HNCS.dcp"
MD_SORTIE = PROJET / "measurements" / "ajustement.md"
FIG_SORTIE = PROJET / "measurements" / "ajustement-courbes-teintes.png"
PLANCHE_SORTIE = PROJET / "measurements" / "planche-tenue-a-part.png"
NOM_CAMERA = "Hasselblad 100-22-Coated6"

KNOTS = np.array([0, .002, .006, .015, .03, .055, .09, .14, .21, .30, .42, .56, .72, .86, 1.0])
LOOK_DIMS = (36, 8, 8)          # teintes, saturations, valeurs
D50 = ca.D50_XYZ
M_PP = ca.PROPHOTO_VERS_XYZ_SDK
M_PP_INV = np.linalg.inv(M_PP)


# ============================================================ couleur : Lab, ΔE2000, perte robuste
def xyz_lab(xyz):
    t = np.asarray(xyz, float) / D50
    f = np.where(t > 216 / 24389, np.cbrt(np.maximum(t, 1e-12)), (24389 / 27 * t + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def de2000(l1, l2):
    """CIEDE2000 entre deux tableaux Lab (n,3)."""
    L1, a1, b1 = l1[..., 0], l1[..., 1], l1[..., 2]
    L2, a2, b2 = l2[..., 0], l2[..., 1], l2[..., 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0.0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm, Cpm = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hm = np.where(np.abs(h1p - h2p) > 180, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2), hs / 2)
    hm = np.where(C1p * C2p == 0, hs, hm)
    T = (1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm))
         + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63)))
    dth = 30 * np.exp(-(((hm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


F_HUBER = 2.0


def perte(de):
    """Perte de Huber (scipy, f_scale = F_HUBER) sur des ΔE2000 : somme, pour comparer des gains."""
    z = (np.asarray(de) / F_HUBER) ** 2
    return float(np.sum(np.where(z <= 1, z, 2 * np.sqrt(z) - 1)))


# ============================================================ données
class Donnees:
    def __init__(self, cam, tgt, jpg, img, neutres, noms=None):
        self.cam, self.tgt, self.jpg, self.img = cam, tgt, jpg, img
        self.neutres = neutres
        self.n_img = len(neutres)
        self.noms = noms if noms is not None else [str(i) for i in range(self.n_img)]
        self.lab_t = xyz_lab(tgt)
        self.lab_j = xyz_lab(jpg) if jpg is not None else None
        b = np.searchsorted(img, np.arange(self.n_img + 1))
        self.sl = [slice(b[i], b[i + 1]) for i in range(self.n_img)]
        self._xy = None

    def vue(self, idx):
        """Sous-ensemble d'échantillons (indices triés), mêmes images."""
        d = Donnees.__new__(Donnees)
        d.cam, d.tgt, d.img = self.cam[idx], self.tgt[idx], self.img[idx]
        d.jpg = None if self.jpg is None else self.jpg[idx]
        d.neutres, d.n_img, d.noms = self.neutres, self.n_img, self.noms
        d.lab_t = self.lab_t[idx]
        d.lab_j = None if self.lab_j is None else self.lab_j[idx]
        b = np.searchsorted(d.img, np.arange(d.n_img + 1))
        d.sl = [slice(b[i], b[i + 1]) for i in range(d.n_img)]
        d._xy = self._xy
        return d

    def xy(self, base):
        """xy de la balance de chaque image : ne dépend que des ColorMatrix (inchangées)."""
        if self._xy is None:
            spec = ca.SpecCouleur(base)
            self._xy = [spec.neutre_vers_xy(n) for n in self.neutres]
        return self._xy


def charger_donnees(chemin=NPZ):
    d = np.load(chemin, allow_pickle=True)
    img = d["image"].astype(int)
    assert np.all(np.diff(img) >= 0), "échantillons non triés par image"
    w = d["wb_as_shot"].astype(float)
    neutres = np.stack([1 / w[:, 0], np.ones(len(w)), 1 / w[:, 2]], -1)     # CameraNeutral = 1/mult, G = 1
    return Donnees(d["cam_rgb"].astype(float), d["phocus_xyz"].astype(float), d["jpeg_xyz"].astype(float),
                   img, neutres, [str(x) for x in d["noms"]])


# ============================================================ profil et chaîne par étapes
def base_adobe():
    p = ca.charger_dcp(ca.DCP_ADOBE)
    import dcp_ecrire
    brut = dcp_ecrire.lire(ca.DCP_ADOBE)
    assert brut["UniqueCameraModel"] == NOM_CAMERA, brut["UniqueCameraModel"]
    return p, brut


class Base:
    """Profil Adobe + ForwardMatrix normalisées (FM·1 = D50)."""

    def __init__(self):
        self.p, self.brut = base_adobe()
        self.fm1 = ca._normaliser_fm(self.p.fm1)
        self.fm2 = ca._normaliser_fm(self.p.fm2)


def matrice_M(E):
    """M = I + E·P avec P·D50 = 0 : M·D50 = D50 (le blanc, donc le neutre, ne bouge pas)."""
    u = np.ones(3)
    P = np.eye(3) - np.outer(D50, u) / (u @ D50)
    return np.eye(3) + np.asarray(E, float).reshape(3, 3) @ P


def courbe_depuis(q, y_fin):
    """Nœuds de la courbe : incréments positifs q (14), normalisés, y(0)=0, y(1)=y_fin."""
    c = np.concatenate([[0.0], np.cumsum(q)])
    return np.stack([KNOTS, c / c[-1] * y_fin], -1)


def q_depuis_courbe(pts):
    y = pts[:, 1]
    return np.maximum(np.diff(y), 1e-4) / 1.0, float(y[-1])


def profil_depuis(base, E, pts, look, offset=0.0):
    M = matrice_M(E)
    p = base.p
    return ca.Profil(cm1=p.cm1, cm2=p.cm2, fm1=M @ base.fm1, fm2=M @ base.fm2, ill1=p.ill1, ill2=p.ill2,
                     hsm1=None, hsm2=None, look=look, look_encodage=1, courbe=pts,
                     exposition_base_profil=float(offset), noir_defaut_aucun=True, nom="HNCS")


def etape1(D, profil, cache_spec=None):
    """RGB caméra -> ProPhoto linéaire borné, par image (RefBaselineABCtoRGB)."""
    spec = ca.SpecCouleur(profil)
    out = np.empty_like(D.cam)
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue
        xy = D.xy(profil)[i]
        cam2pcs, blanc = spec.camera_vers_pcs(xy)
        m = M_PP_INV @ cam2pcs
        out[s] = np.clip(np.minimum(D.cam[s], blanc) @ m.T, 0.0, 1.0)
    return out


def exposer(rgb, expo):
    white = 1.0 / 2.0 ** max(0.0, expo)
    return ca._interp_1d(ca._table_1d(lambda x: ca._rampe_exposition(x, white, 0.0)), rgb)


def post_look(D, rgb1, expo_img, look):
    out = np.empty_like(rgb1)
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue
        r = exposer(rgb1[s], expo_img[i])
        out[s] = r if look is None else ca.appliquer_table_hsv(r, look, 1)
    return out


def tab_tonalite(pts, expo):
    f = ca.SplineAdobe(pts)
    return ca._table_1d(lambda x: f(np.clip(ca._exposition_negative(x, expo), 0.0, 1.0)))


def tonalite(D, P, pts, expo_img):
    out = np.empty_like(P)
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue
        out[s] = ca._appliquer_tonalite(P[s], tab_tonalite(pts, expo_img[i]))
    return out


def xyz_depuis(rgb):
    return rgb @ M_PP.T


def de_modele(D, profil_pts_look, rgb1, expo_img, ref="t"):
    pts, look = profil_pts_look
    P = post_look(D, rgb1, expo_img, look)
    xyz = xyz_depuis(tonalite(D, P, pts, expo_img))
    return de2000(xyz_lab(xyz), D.lab_t if ref == "t" else D.lab_j)


# ============================================================ gains par image
def meilleur_gain(f_de, lo=-2.5, hi=2.5):
    """f_de(g) -> ΔE2000 (n,) pour un gain g (IL).  Grille puis raffinement borné (perte de Huber)."""
    grille = np.linspace(lo, hi, 11)
    v = [perte(f_de(g)) for g in grille]
    k = int(np.argmin(v))
    a, b = grille[max(k - 1, 0)], grille[min(k + 1, len(grille) - 1)]
    r = minimize_scalar(lambda g: perte(f_de(g)), bounds=(a, b), method="bounded", options={"xatol": 2e-3})
    return float(r.x)


def ajuster_gains(D, rgb1, pts, look, gains, images, offset=0.0, ref="t"):
    g = gains.copy()
    lab = D.lab_t if ref == "t" else D.lab_j
    for i in images:
        s = D.sl[i]
        if s.stop == s.start:
            continue

        def f(x, s=s, i=i):
            e = x + offset
            P = (lambda r: r if look is None else ca.appliquer_table_hsv(r, look, 1))(exposer(rgb1[s], e))
            out = ca._appliquer_tonalite(P, tab_tonalite(pts, e))
            return de2000(xyz_lab(xyz_depuis(out)), lab[s])
        g[i] = meilleur_gain(f)
    return g


# ============================================================ courbe et FM
def ajuster_courbe(D, P, pts0, expo_img, log=None, maxiter=40):
    """Courbe seule (P = rgb après exposition et LookTable, figé)."""
    q0, yf0 = q_depuis_courbe(pts0)
    x0 = np.concatenate([q0 / q0.sum() * 1.0, [yf0]])

    def pts_de(x):
        return courbe_depuis(np.maximum(x[:-1], 1e-5), x[-1])

    dense = np.linspace(0, 1, 400)

    def resid(x):
        pts = pts_de(x)
        xyz = xyz_depuis(tonalite(D, P, pts, expo_img))
        r = de2000(xyz_lab(xyz), D.lab_t)
        mono = np.diff(ca.SplineAdobe(pts)(dense))
        return np.concatenate([r, 300.0 * np.maximum(-mono, 0.0)])

    lb = np.concatenate([np.full(len(q0), 1e-5), [0.95]])
    ub = np.concatenate([np.full(len(q0), 1.0), [1.0]])
    r = least_squares(resid, np.clip(x0, lb + 1e-9, ub - 1e-9), bounds=(lb, ub), loss="huber", f_scale=F_HUBER,
                      diff_step=1e-3, max_nfev=maxiter, x_scale=np.concatenate([np.full(len(q0), 0.05), [0.01]]))
    return pts_de(r.x)


def ajuster_fm_courbe(D, base, E0, pts0, look, expo_img, maxiter=25):
    """FM (E, 9 paramètres) + courbe, ensemble, avec LookTable figée."""
    q0, yf0 = q_depuis_courbe(pts0)
    nq = len(q0)
    x0 = np.concatenate([q0 / q0.sum(), [yf0], np.asarray(E0).ravel()])
    dense = np.linspace(0, 1, 400)

    def resid(x):
        pts = courbe_depuis(np.maximum(x[:nq], 1e-5), x[nq])
        E = x[nq + 1:]
        prof = profil_depuis(base, E, pts, look)
        rgb1 = etape1(D, prof)
        P = post_look(D, rgb1, expo_img, look)
        xyz = xyz_depuis(tonalite(D, P, pts, expo_img))
        r = de2000(xyz_lab(xyz), D.lab_t)
        mono = np.diff(ca.SplineAdobe(pts)(dense))
        return np.concatenate([r, 300.0 * np.maximum(-mono, 0.0), 3.0 * E])      # ridge léger sur E

    lb = np.concatenate([np.full(nq, 1e-5), [0.95], np.full(9, -0.4)])
    ub = np.concatenate([np.full(nq, 1.0), [1.0], np.full(9, 0.4)])
    sc = np.concatenate([np.full(nq, 0.05), [0.01], np.full(9, 0.02)])
    r = least_squares(resid, np.clip(x0, lb + 1e-9, ub - 1e-9), bounds=(lb, ub), loss="huber", f_scale=F_HUBER,
                      diff_step=1e-3, max_nfev=maxiter, x_scale=sc)
    return r.x[nq + 1:].reshape(3, 3), courbe_depuis(np.maximum(r.x[:nq], 1e-5), r.x[nq])


# ============================================================ LookTable : régression creuse en HSV
def poids_grille(hsv_enc, H, S, V):
    """Poids trilinéaires (sparse N x K) comme appliquer_table_hsv : hsv_enc = (h in [0,6), s, v encodée)."""
    h, s, v = hsv_enc[:, 0], hsv_enc[:, 1], hsv_enc[:, 2]
    N = len(h)
    hs, ss, vs = h * (H / 6.0), s * (S - 1), v * (V - 1)
    h0 = np.minimum(np.floor(hs).astype(int), H - 1)
    h1 = np.where(h0 >= H - 1, 0, h0 + 1)
    s0 = np.minimum(np.floor(ss).astype(int), S - 2)
    v0 = np.minimum(np.floor(vs).astype(int), V - 2)
    hf, sf, vf = hs - h0, ss - s0, vs - v0
    rows, cols, vals = [], [], []
    ar = np.arange(N)
    for dv, wv in ((0, 1 - vf), (1, vf)):
        for dh, wh in ((0, 1 - hf), (1, hf)):
            for ds, wsat in ((0, 1 - sf), (1, sf)):
                rows.append(ar)
                cols.append((v0 + dv) * H * S + (h0 if dh == 0 else h1) * S + s0 + ds)
                vals.append(wv * wh * wsat)
    return sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(N, H * S * V))


def laplacien(H, S, V):
    """Arêtes de la grille (teinte circulaire) -> matrice D (E x K) des différences."""
    idx = np.arange(H * S * V).reshape(V, H, S)
    paires = []
    paires.append((idx, np.roll(idx, -1, axis=1)))          # teinte (circulaire)
    paires.append((idx[:, :, :-1], idx[:, :, 1:]))           # saturation
    paires.append((idx[:-1], idx[1:]))                       # valeur
    ls = []
    for a, b in paires:
        a, b = a.ravel(), b.ravel()
        n = len(a)
        m = sparse.csr_matrix((np.concatenate([np.ones(n), -np.ones(n)]),
                               (np.concatenate([np.arange(n)] * 2), np.concatenate([a, b]))), shape=(n, H * S * V))
        ls.append(m)
    return ls      # [teinte, saturation, valeur]


def inverse_tonalite(pts, expo):
    tab = tab_tonalite(pts, expo)
    xg = np.arange(4097) / 4096.0
    tm = np.maximum.accumulate(tab) + 1e-9 * xg
    return lambda y: np.interp(y, tm, xg)


def ajuster_look(D, rgb1, pts, expo_img, poids_de, lam, dims=LOOK_DIMS):
    """LookTable (V,H,S,3) par régression : cible = Phocus ramené avant la courbe (inverse sur max/min)."""
    H, S, V = dims
    K = H * S * V
    src = np.empty_like(rgb1)
    pre = np.empty_like(rgb1)
    t_rgb = np.clip(D.tgt @ M_PP_INV.T, 0.0, 1.0)
    ok = np.zeros(len(rgb1), bool)
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue
        src[s] = exposer(rgb1[s], expo_img[i])
        tinv = inverse_tonalite(pts, expo_img[i])
        t = t_rgb[s]
        hi_t, lo_t = t.max(-1, keepdims=True), t.min(-1, keepdims=True)
        hi, lo = tinv(hi_t), tinv(lo_t)
        e = hi_t - lo_t
        pre[s] = np.where(e > 1e-6, lo + (hi - lo) * (t - lo_t) / np.where(e > 1e-6, e, 1.0), hi)
        ok[s] = (hi_t[:, 0] < 0.985) & (hi_t[:, 0] > 2e-3)
    hs, ht = ca.rgb_vers_hsv(src), ca.rgb_vers_hsv(pre)
    ok &= (hs[:, 2] < 0.99) & (hs[:, 2] > 1e-3)
    sv, sT = hs[:, 1], ht[:, 1]
    ve_s, ve_t = ca._srgb_encode(hs[:, 2]), ca._srgb_encode(ht[:, 2])
    W = poids_grille(np.stack([hs[:, 0], sv, ve_s], -1), H, S, V)
    w = poids_de(ok)
    w = np.where(ok, w, 0.0)
    w = w / max(w[ok].mean(), 1e-9)
    dh = (((ht[:, 0] - hs[:, 0] + 3.0) % 6.0) - 3.0)                  # en unités de 60 degrés (teinte DNG 0..6)
    smin = np.minimum(sv, sT)
    a_h = w * (smin * hs[:, 2]) ** 2 * (np.pi / 3) ** 2
    a_s = w * sv ** 2
    y_s = np.clip(sT / np.maximum(sv, 1e-3), 0.2, 4.0)
    a_v = w * ve_s ** 2
    y_v = np.clip(ve_t / np.maximum(ve_s, 1e-3), 0.3, 3.0)
    Ls = laplacien(H, S, V)
    Lreg = lam["h"] * (Ls[0].T @ Ls[0]) + lam["s"] * (Ls[1].T @ Ls[1]) + lam["v"] * (Ls[2].T @ Ls[2])
    idx = np.arange(K).reshape(V, H, S)
    pin = np.zeros(K)
    pin[idx[:, :, 0].ravel()] = 1e6                                   # saturation 0 : neutre strict
    out = np.zeros((V, H, S, 3))
    for c, (a, y, x0) in enumerate(((a_h, dh, 0.0), (a_s, y_s, 1.0), (a_v, y_v, 1.0))):
        Wa = W.T @ sparse.diags(a)
        A = Wa @ W + Lreg + sparse.diags(lam["0"] + pin)
        b = Wa @ y + (lam["0"] + pin) * x0
        x = spsolve(A.tocsc(), b)
        out[..., c] = x.reshape(V, H, S)
    out[..., 0] = np.clip(out[..., 0], -1.0, 1.0) * 60.0              # degrés
    out[..., 1] = np.clip(out[..., 1], 0.2, 3.0)
    out[..., 2] = np.clip(out[..., 2], 0.3, 2.0)
    out[:, :, 0, :] = (0.0, 1.0, 1.0)
    return out


def look_neutre(dims=LOOK_DIMS):
    H, S, V = dims
    t = np.zeros((V, H, S, 3))
    t[..., 1:] = 1.0
    return t


# ============================================================ boucle d'ajustement
def poids_huber(D, rgb1, pts, look, expo_img):
    de = de_modele(D, (pts, look), rgb1, expo_img)
    w = np.minimum(1.0, 2.5 / np.maximum(de, 1e-6))
    return lambda ok: w


def ajuster(D, fit_img, log=print, rapide=False, lams=(0.005, 0.02, 0.08), n_sub=1200, graine=0):
    """D : Donnees ; fit_img : indices d'images ajustées.  Retourne dict(E, pts, look, gains, lam)."""
    t0 = time.time()
    base = Base()
    rng = np.random.default_rng(graine)
    masque = np.isin(D.img, fit_img)
    idx_fit = np.nonzero(masque)[0]
    Df = D.vue(idx_fit)
    sel = []
    for i in fit_img:
        s = np.nonzero(Df.img == i)[0]
        sel.append(np.sort(rng.choice(s, min(n_sub, len(s)), replace=False)))
    Ds = Df.vue(np.concatenate(sel))
    n = D.n_img
    E = np.zeros((3, 3))
    pts = np.stack([KNOTS, np.minimum(ca.courbe_acr3(KNOTS), 1.0)], -1)
    look = look_neutre()
    gains = np.zeros(n)
    k_iter = (1, 1) if rapide else (3, 2)
    maxit = 8 if rapide else 40

    def prof():
        return profil_depuis(base, E, pts, look)

    def rgb1_de(Dx):
        return etape1(Dx, prof())

    def alt(nb, tag):
        nonlocal pts, gains
        r1 = rgb1_de(Ds)
        for _ in range(nb):
            gains = ajuster_gains(Ds, r1, pts, look, gains, fit_img)
            gains[fit_img] -= np.median(gains[fit_img])               # jauge : médiane = 0 IL
            P = post_look(Ds, r1, gains, look)
            pts = ajuster_courbe(Ds, P, pts, gains, maxiter=maxit)
        de = de_modele(Ds, (pts, look), r1, gains)
        log(f"  [{time.time() - t0:5.0f}s] {tag}: ΔE2000 médiane {np.median(de):.3f}, 90e {np.percentile(de, 90):.3f}")

    log("tour 0 : gains + courbe, sans LookTable")
    alt(k_iter[0], "gains/courbe")
    log("tour 0 : FM + courbe")
    E, pts = ajuster_fm_courbe(Ds, base, E, pts, look, gains, maxiter=4 if rapide else 25)
    alt(k_iter[1], "après FM")

    # choix du lissage par validation interne (une image fit sur quatre, hors ajustement de ce choix)
    val = np.array([i for i in fit_img if i % 4 == 1])
    tr = np.array([i for i in fit_img if i % 4 != 1])
    lam_ch = None
    if len(val) and not rapide and len(lams) > 1:
        r1f = rgb1_de(Df)
        Dtr = Df.vue(np.nonzero(np.isin(Df.img, tr))[0])
        Dva = Df.vue(np.nonzero(np.isin(Df.img, val))[0])
        r1tr, r1va = rgb1_de(Dtr), rgb1_de(Dva)
        w0 = poids_huber(Dtr, r1tr, pts, look, gains)
        res = {}
        for lm in lams:
            lk = ajuster_look(Dtr, r1tr, pts, gains, w0, dict(h=lm, s=lm, v=lm, **{"0": lm / 10}))
            g = ajuster_gains(Dva, r1va, pts, lk, gains, val)
            de = de_modele(Dva, (pts, lk), r1va, g)
            res[lm] = float(np.median(de)) + 0.25 * float(np.percentile(de, 90))
            log(f"  lissage {lm}: validation interne médiane+0,25·p90 = {res[lm]:.3f}")
        lam_ch = min(res, key=res.get)
    lm = lam_ch if lam_ch is not None else lams[min(1, len(lams) - 1)]
    lam = dict(h=lm, s=lm, v=lm, **{"0": lm / 10})
    log(f"lissage retenu : {lm}")

    tours = 2 if rapide else 3
    for t in range(tours):
        r1f = rgb1_de(Df)
        w = poids_huber(Df, r1f, pts, look, gains)
        look = ajuster_look(Df, r1f, pts, gains, w, lam)
        alt(k_iter[1], f"tour {t + 1} : look + gains/courbe")
        if t == 1 and not rapide:
            E, pts = ajuster_fm_courbe(Ds, base, E, pts, look, gains, maxiter=20)
            alt(1, f"tour {t + 1} : FM+courbe avec look")
    r1f = rgb1_de(Df)
    w = poids_huber(Df, r1f, pts, look, gains)
    look = ajuster_look(Df, r1f, pts, gains, w, lam)
    # dernier réglage des gains avec le profil final (images ajustées), puis résidu de médiane -> offset
    r1 = rgb1_de(Ds)
    gains = ajuster_gains(Ds, r1, pts, look, gains, fit_img)
    offset = float(np.median(gains[fit_img]))
    log(f"  [{time.time() - t0:5.0f}s] médiane des gains finale {offset:+.3f} IL -> BaselineExposureOffset")
    return dict(E=E, pts=pts, look=look, offset=offset, lam=lm, base=base)


# ============================================================ DCP
def dcp_dict(res):
    base = res["base"]
    p = profil_depuis(base, res["E"], res["pts"], res["look"], res["offset"])
    H, S, V = LOOK_DIMS
    b = base.brut
    return {
        "UniqueCameraModel": NOM_CAMERA,
        "ColorMatrix1": b["ColorMatrix1"], "ColorMatrix2": b["ColorMatrix2"],
        "CalibrationIlluminant1": b["CalibrationIlluminant1"], "CalibrationIlluminant2": b["CalibrationIlluminant2"],
        "ProfileName": "HNCS", "ProfileCopyright": "Thomas Hammoudi", "ProfileEmbedPolicy": [0],
        "ForwardMatrix1": p.fm1.ravel().tolist(), "ForwardMatrix2": p.fm2.ravel().tolist(),
        "ProfileLookTableDims": [H, S, V],
        "ProfileLookTableData": np.asarray(res["look"], np.float32).ravel().tolist(),
        "ProfileLookTableEncoding": [1],
        "ProfileToneCurve": np.asarray(res["pts"], float).ravel().tolist(),
        "BaselineExposureOffset": [float(res["offset"])], "DefaultBlackRender": [1],
    }


def ecrire_dcp(res, chemin):
    chemin = pathlib.Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    dcp_ecrire.ecrire(str(chemin), dcp_dict(res))
    return ca.charger_dcp(chemin)


# ============================================================ évaluation (chaîne officielle, DCP relu)
def evaluer(D, profil, ref="t", images=None, exposition_base=0.0):
    """Gain par image (1D, Huber) puis ΔE2000 (n,) pour tous les échantillons, via rendre_xyz_d50."""
    lab = D.lab_t if ref == "t" else D.lab_j
    gains = np.zeros(D.n_img)
    de = np.zeros(len(D.cam))
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue

        def f(g, s=s, i=i):
            xyz = ca.rendre_xyz_d50(D.cam[s], D.neutres[i], profil, g, exposition_base=exposition_base)
            return de2000(xyz_lab(xyz), lab[s])
        g = meilleur_gain(f)
        gains[i] = g
        de[s] = f(g)
    return gains, de


def stats(de):
    return float(np.median(de)), float(np.percentile(de, 90))


def decalage_wb(D, pr, gains, fit_img, held_img, n_sub=500):
    """Décalage global de balance (CameraNeutral x (1+dR, 1, 1+dB)) qui rapproche Phocus : ce qu'un profil ne peut pas
    porter (la ForwardMatrix est renormalisée pour que le neutre reste neutre).  Ajusté sur les images d'ajustement."""
    from scipy.optimize import minimize
    rng = np.random.default_rng(3)
    idx = np.sort(np.concatenate([rng.choice(np.arange(s.start, s.stop), min(n_sub, s.stop - s.start), replace=False)
                                  for i, s in enumerate(D.sl) if i in set(fit_img)]))
    Df = D.vue(idx)

    def de_pour(Dx, p):
        out = np.zeros(len(Dx.cam))
        for i, s in enumerate(Dx.sl):
            if s.stop == s.start:
                continue
            n = Dx.neutres[i] * np.array([1 + p[0], 1, 1 + p[1]])
            out[s] = de2000(xyz_lab(ca.rendre_xyz_d50(Dx.cam[s], n, pr, gains[i])), Dx.lab_t[s])
        return out
    r = minimize(lambda p: perte(de_pour(Df, p)), [0.0, 0.0], method="Nelder-Mead",
                 options=dict(xatol=2e-3, fatol=1e-3, maxiter=60))
    p = r.x
    res = {}
    for nom, imgs in (("ajustement", fit_img), ("tenue à part", held_img)):
        Dm = D.vue(np.nonzero(np.isin(D.img, imgs))[0])
        res[nom] = (stats(de_pour(Dm, [0, 0])), stats(de_pour(Dm, p)))
    base = Base().p
    n0 = np.median(D.neutres, axis=0)
    t0 = ca.xy_vers_temp(ca.SpecCouleur(base).neutre_vers_xy(n0))
    t1 = ca.xy_vers_temp(ca.SpecCouleur(base).neutre_vers_xy(n0 * np.array([1 + p[0], 1, 1 + p[1]])))
    return p, res, (t0, t1)


# ============================================================ self-test
def _verites_synthetiques(base, D, look_vrai, pts_vrais, gains_vrais):
    prof = profil_depuis(base, np.zeros((3, 3)), pts_vrais, look_vrai)
    xyz = np.empty_like(D.cam)
    for i, s in enumerate(D.sl):
        xyz[s] = ca.rendre_xyz_d50(D.cam[s], D.neutres[i], prof, gains_vrais[i])
    return xyz


def self_test():
    ok = True

    def verif(nom, cond, detail=""):
        nonlocal ok
        print(("  ok   " if cond else "  ECHEC"), nom, detail)
        ok &= bool(cond)

    print("ajuster.py --self-test")
    D0 = charger_donnees()
    # 1. ΔE2000 maison contre colour
    rng = np.random.default_rng(1)
    a, b = rng.uniform(0.02, 0.9, (500, 3)), rng.uniform(0.02, 0.9, (500, 3))
    ref = ca._delta_e_2000(a, b)
    verif("ΔE2000 maison = colour", np.max(np.abs(de2000(xyz_lab(a), xyz_lab(b)) - ref)) < 2e-3,
          f"écart max {np.max(np.abs(de2000(xyz_lab(a), xyz_lab(b)) - ref)):.1e}")

    # 2. jeu synthétique : 8 vraies balances, 700 vrais RGB caméra par image, rendus par chaine_adobe
    imgs = np.arange(8) * 4 + 1
    sel = []
    for i in imgs:
        s = np.nonzero(D0.img == i)[0]
        sel.append(np.sort(rng.choice(s, 700, replace=False)))
    sel = np.concatenate(sel)
    remap = {int(v): k for k, v in enumerate(imgs)}
    cam = D0.cam[sel]
    img = np.array([remap[int(v)] for v in D0.img[sel]])
    neutres = D0.neutres[imgs]
    base = Base()
    # LookTable vraie, connue : teinte +-8 deg, saturation x(1+-0.15), valeur x(1+-0.05), saturation 0 neutre
    H, S, V = LOOK_DIMS
    look_v = look_neutre()
    hh = (np.arange(H) / H * 2 * np.pi)[None, :, None]
    sat = (np.arange(S) / (S - 1))[None, None, :]
    look_v[..., 0] = 8.0 * np.sin(hh) * sat
    look_v[..., 1] = 1 + 0.15 * np.cos(hh + 1.0) * sat
    look_v[..., 2] = 1 + 0.05 * np.sin(2 * hh) * sat
    look_v[:, :, 0, :] = (0.0, 1.0, 1.0)
    pts_v = np.stack([KNOTS, np.minimum(ca.courbe_acr3(KNOTS) ** 1.08, 1.0)], -1)
    gains_v = np.array([-0.4, -0.2, -0.1, 0.0, 0.0, 0.15, 0.3, 0.5])
    gains_v -= np.median(gains_v)
    Dtmp = Donnees(cam, np.ones_like(cam) * 0.3, None, img, neutres)
    tgt = _verites_synthetiques(base, Dtmp, look_v, pts_v, gains_v)
    Ds = Donnees(cam, tgt, tgt.copy(), img, neutres)
    fit = np.array([0, 1, 2, 4, 5, 6])          # images 3 et 7 tenues à part
    t0 = time.time()
    res = ajuster(Ds, fit, log=lambda *_: None, rapide=True, n_sub=500)
    print(f"  (ajustement synthétique : {time.time() - t0:.0f} s)")
    # DCP écrit dans tmp-ajuster, relu, rendu avec la chaîne officielle
    TMP.mkdir(parents=True, exist_ok=True)
    chem = TMP / "selftest.dcp"
    pr = ecrire_dcp(res, chem)
    g, de = evaluer(Ds, pr)
    tenue = np.isin(Ds.img, [3, 7])
    verif("synthétique : ΔE2000 médiane (ajustement)", np.median(de[~tenue]) < 0.5, f"{np.median(de[~tenue]):.3f}")
    verif("synthétique : ΔE2000 médiane (tenue à part)", np.median(de[tenue]) < 0.6, f"{np.median(de[tenue]):.3f}")
    verif("synthétique : 90e centile (tenue à part)", np.percentile(de[tenue], 90) < 1.5,
          f"{np.percentile(de[tenue], 90):.3f}")
    gm = g - np.median(g[fit])
    verif("gains retrouvés (à la jauge près)", np.max(np.abs(gm - gains_v)) < 0.08,
          f"écart max {np.max(np.abs(gm - gains_v)):.3f} IL")
    lk = pr.look
    verif("cases saturation 0 strictement neutres", np.all(lk[:, :, 0, :] == np.array([0, 1, 1], np.float32)))
    verif("LookTable bornée (pas de valeurs folles)", lk[..., 1].min() >= 0.2 and lk[..., 1].max() <= 3.0
          and lk[..., 2].min() >= 0.3 and lk[..., 2].max() <= 2.0 and np.abs(lk[..., 0]).max() <= 60.0)
    dense = np.linspace(0, 1, 4097)
    verif("courbe monotone (spline d'Adobe, 4097 pts)", np.all(np.diff(ca.SplineAdobe(pr.courbe)(dense)) >= -1e-9))
    verif("courbe (0,0) et y(1) <= 1", pr.courbe[0, 0] == 0 and pr.courbe[0, 1] == 0 and pr.courbe[-1, 1] <= 1 + 1e-9)
    # neutre reste neutre : rampe de gris à travers le DCP relu
    for i in (0, 5):
        t = np.geomspace(0.003, 0.95, 40)[:, None] * Ds.neutres[i][None, :]
        lab = xyz_lab(ca.rendre_xyz_d50(t, Ds.neutres[i], pr, 0.0))
        verif(f"neutre reste neutre (balance {i})", np.max(np.hypot(lab[:, 1], lab[:, 2])) < 1.0,
              f"chroma max {np.max(np.hypot(lab[:, 1], lab[:, 2])):.2f}")
    # aller-retour DCP : nos étapes = rendre_xyz_d50 ; ré-ecriture identique
    prof_mem = profil_depuis(res["base"], res["E"], res["pts"], res["look"], res["offset"])
    Dm = Ds.vue(np.arange(0, len(Ds.cam), 7))
    r1 = etape1(Dm, prof_mem)
    exp = np.full(Dm.n_img, res["offset"])
    P = post_look(Dm, r1, exp + 0.2, res["look"])
    mine = xyz_depuis(tonalite(Dm, P, res["pts"], exp + 0.2))
    off = np.concatenate([ca.rendre_xyz_d50(Dm.cam[s], Dm.neutres[i], prof_mem, 0.2 - 0.0 + 0.0)
                          for i, s in enumerate(Dm.sl)])
    verif("étapes maison = rendre_xyz_d50", np.max(np.abs(mine - off)) < 1e-9, f"{np.max(np.abs(mine - off)):.1e}")
    brut = dcp_ecrire.lire(str(chem))
    verif("DCP : UniqueCameraModel, ProfileName, copyright",
          brut["UniqueCameraModel"] == NOM_CAMERA and brut["ProfileName"] == "HNCS"
          and brut["ProfileCopyright"] == "Thomas Hammoudi")
    verif("DCP : pas de HueSatMap", "ProfileHueSatMapData1" not in brut)
    # 3. profil identité : cibles rendues par un profil à LookTable neutre et courbe ACR3 -> table proche de neutre
    pts_i = np.stack([KNOTS, np.minimum(ca.courbe_acr3(KNOTS), 1.0)], -1)
    tgt_i = _verites_synthetiques(base, Dtmp, look_neutre(), pts_i, np.zeros(8))
    Di = Donnees(cam, tgt_i, tgt_i.copy(), img, neutres)
    res_i = ajuster(Di, fit, log=lambda *_: None, rapide=True, n_sub=500)
    pri = ecrire_dcp(res_i, TMP / "selftest-identite.dcp")
    gi, dei = evaluer(Di, pri)
    verif("identité : ΔE2000 médiane", np.median(dei) < 0.25, f"{np.median(dei):.3f}")
    verif("identité : gains ~ 0", np.max(np.abs(gi)) < 0.08, f"{np.max(np.abs(gi)):.3f}")
    verif("identité : LookTable proche du neutre",
          np.median(np.abs(pri.look[..., 1] - 1)) < 0.03 and np.median(np.abs(pri.look[..., 0])) < 2.0,
          f"|ΔS| médian {np.median(np.abs(pri.look[..., 1] - 1)):.3f}")
    print("RÉSULTAT :", "tout passe" if ok else "ÉCHEC")
    return 0 if ok else 1


# ============================================================ livrables
def _police(taille):
    """Police avec accents et grec (la police par défaut de PIL n'a pas les accents)."""
    from PIL import ImageFont
    for c in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        if os.path.exists(c):
            return ImageFont.truetype(c, taille)
    return ImageFont.load_default(size=taille)


def figure(res, pr_hncs, pr_adobe, D, gains_h, chemin):
    from PIL import Image, ImageDraw, ImageFont
    W, Hh = 1500, 1000
    im = Image.new("RGB", (W, Hh), (250, 250, 250))
    dr = ImageDraw.Draw(im)
    f_t = _police(26)
    f_m = _police(18)
    dr.text((30, 18), "Profil HNCS : rampe de gris et teintes, avant (Adobe Standard) / après (HNCS)", fill=(0, 0, 0), font=f_t)
    # --- panneau 1 : rampe de gris
    x0, y0, w, h = 90, 110, 600, 600
    dr.rectangle([x0, y0, x0 + w, y0 + h], outline=(0, 0, 0))
    dr.text((x0, y0 - 38), "Rampe de gris (X en sRGB de la lumière de scène, Y : sortie)", fill=(0, 0, 0), font=f_m)
    n0 = D.neutres[0]
    t = np.linspace(0.0, 1.0, 400)
    lin = ca._srgb_decode(t)
    cam = lin[:, None] * n0[None, :]
    for pr, col, nom, gg in ((pr_adobe, (200, 60, 60), "Adobe Standard (0 IL)", 0.0),
                             (pr_hncs, (30, 90, 200), "HNCS (0 IL)", 0.0)):
        y = ca.rendre_xyz_d50(cam, n0, pr, gg)[:, 1]
        pts = [(x0 + tt * w, y0 + h - ca._srgb_encode(min(max(yy, 0), 1)) * h) for tt, yy in zip(t, y)]
        dr.line(pts, fill=col, width=3)
    # points Phocus quasi neutres (x = valeur après exposition et look, avant courbe)
    r1 = etape1(D, pr_hncs)
    P = post_look(D, r1, gains_h + pr_hncs.exposition_base_profil, pr_hncs.look)
    lab = D.lab_t
    neutre = np.hypot(lab[:, 1], lab[:, 2]) < 4
    rng = np.random.default_rng(0)
    ids = rng.choice(np.nonzero(neutre)[0], min(2500, neutre.sum()), replace=False)
    for k in ids:
        xx = ca._srgb_encode(P[k].mean())
        yy = ca._srgb_encode(min(D.tgt[k, 1], 1.0))
        dr.ellipse([x0 + xx * w - 1.5, y0 + h - yy * h - 1.5, x0 + xx * w + 1.5, y0 + h - yy * h + 1.5], fill=(60, 60, 60))
    dr.line([(x0, y0 + h), (x0 + w, y0)], fill=(190, 190, 190), width=1)
    yl = y0 + h + 14
    for col, nom in (((200, 60, 60), "Adobe Standard (exposition 0)"), ((30, 90, 200), "HNCS (exposition 0)"),
                     ((60, 60, 60), "Phocus : blocs quasi neutres, avec le gain de chaque image")):
        dr.rectangle([x0, yl + 4, x0 + 22, yl + 16], fill=col)
        dr.text((x0 + 32, yl), nom, fill=(0, 0, 0), font=f_m)
        yl += 28
    # --- panneau 2 : bandes de teintes
    bx, by = 760, 110
    dr.text((bx, by - 38), "Teintes (36 pas), même entrée caméra", fill=(0, 0, 0), font=f_m)
    nh = 36
    sw = 20
    # entrée : ProPhoto linéaire -> caméra par la matrice de HNCS pour une balance de jour
    xy = D.xy(Base().p)[0]
    spec = ca.SpecCouleur(pr_hncs)
    cam2pcs, blanc = spec.camera_vers_pcs(xy)
    m = M_PP_INV @ cam2pcs
    inv_m = np.linalg.inv(m)
    ligne = 0
    for (sat_i, val_i) in ((0.35, 0.35), (0.7, 0.35), (0.9, 0.55)):
        hsv = np.stack([np.arange(nh) / nh * 6.0, np.full(nh, sat_i), np.full(nh, val_i)], -1)
        pp = ca.hsv_vers_rgb(hsv)
        camc = pp @ inv_m.T
        dr.text((bx, by + ligne * 250 - 2), f"saturation {sat_i}, valeur {val_i}", fill=(0, 0, 0), font=f_m)
        for k, (pr, nom) in enumerate(((None, "entrée (matrice seule)"), (pr_adobe, "Adobe Standard"), (pr_hncs, "HNCS"))):
            if pr is None:
                xyz = pp @ M_PP.T
                lin_s = np.clip(xyz @ np.linalg.inv(ca.SRGB_VERS_XYZ_D50).T, 0, 1)
                col = np.clip(ca._srgb_encode(lin_s) * 255 + 0.5, 0, 255).astype(int)
            else:
                col = ca.rendre_srgb(camc, D.neutres[0], pr, 0.0)
            yy = by + ligne * 250 + 22 + k * 62
            for j in range(nh):
                dr.rectangle([bx + j * sw, yy, bx + j * sw + sw - 1, yy + 52], fill=tuple(int(c) for c in col[j]))
            dr.text((bx + nh * sw + 8, yy + 16), nom, fill=(0, 0, 0), font=f_m)
        ligne += 1
    dr.text((30, Hh - 40), "Chaîne : chaine_adobe.py, DCP relu.  Phocus = référence principale.", fill=(80, 80, 80), font=f_m)
    im.save(chemin)


def planche(pr_hncs, gains_h, D, chemin, images=("B0000586", "B0000594", "B0000612", "B0000710")):
    """4 images tenues à part, rendues à l'échelle d'un bloc de 16 px : Phocus | notre profil."""
    import rawpy
    from PIL import Image, ImageDraw, ImageFont
    import echantillons as E
    f_t = _police(26)
    f_m = _police(20)
    lignes = []
    m_srgb_inv = np.linalg.inv(ca.SRGB_VERS_XYZ_D50)

    def en_srgb(xyz):
        lin = np.clip(xyz @ m_srgb_inv.T, 0, 1)
        return np.clip(ca._srgb_encode(lin) * 255 + 0.5, 0, 255).astype(np.uint8)
    for nom in images:
        num = D.noms.index(nom)
        z = np.load(C / "echantillons" / f"{nom}.npz", allow_pickle=True)
        nby, nbx = [int(v) for v in z["grille"]]
        dy, dx = [int(v) for v in z["decalage_raw"]]
        rot = int(z["rot_raw"])
        r = rawpy.imread(str(C / "phocus-entree" / f"{nom}.3FR"))
        raw = r.postprocess(half_size=True, output_color=rawpy.ColorSpace.raw, gamma=(1, 1), no_auto_bright=True,
                            user_wb=[1, 1, 1, 1], output_bps=16)
        r.close()
        if rot:
            raw = np.rot90(raw, rot).copy()
        m_raw = np.zeros((nby, nbx, 3), np.float32)
        pas = 8
        for b0 in range(0, nby, pas):
            b1 = min(nby, b0 + pas)
            a = raw[dy + b0 * 8:dy + b1 * 8, dx:dx + nbx * 8].astype(np.float32) / 65535
            m_raw[b0:b1] = a.reshape(b1 - b0, 8, nbx, 8, 3).mean((1, 3))
        del raw
        d = E.lire_tiff(C / "phocus-sortie" / f"B_{nom[-4:]}.tif")
        mm = np.memmap(C / "phocus-sortie" / f"B_{nom[-4:]}.tif", dtype=">u2", mode="r", offset=d["offset"],
                       shape=(d["h"], d["w"], 3))
        m_pho = np.zeros((nby, nbx, 3), np.float32)
        for b0 in range(0, nby, pas):
            b1 = min(nby, b0 + pas)
            a = np.asarray(mm[b0 * 16:b1 * 16, :nbx * 16], np.float32) / 65535
            m_pho[b0:b1] = a.reshape(b1 - b0, 16, nbx, 16, 3).mean((1, 3))
        del mm
        # contrôle : les blocs échantillonnés retrouvent bien cam_rgb (recalage de la planche)
        ok = (np.abs(m_raw[z["by"], z["bx"]] - z["cam_rgb"]).max() < 2e-3)
        assert ok, f"{nom} : recalage de la planche différent des échantillons"
        g = gains_h[num]
        xyz = ca.rendre_xyz_d50(m_raw.reshape(-1, 3), D.neutres[num], pr_hncs, g)
        im_n = en_srgb(xyz).reshape(nby, nbx, 3)
        im_p = en_srgb(E.decode_adobe(m_pho.astype(np.float64))).reshape(nby, nbx, 3)
        de = de2000(xyz_lab(xyz), xyz_lab(E.decode_adobe(m_pho.astype(np.float64)).reshape(-1, 3)))
        lignes.append((nom, g, im_p, im_n, float(np.median(de))))
        print(f"  planche : {nom} ok")
    wi = max(l[2].shape[1] for l in lignes)
    hi = max(l[2].shape[0] for l in lignes)
    marge, tete = 20, 90
    W = 2 * wi + 3 * marge
    H = tete + len(lignes) * (hi + 60) + marge
    im = Image.new("RGB", (W, H), (245, 245, 245))
    dr = ImageDraw.Draw(im)
    dr.text((marge, 16), "Images tenues à part : Phocus (HNCS) | profil HNCS ajusté (rendu Adobe, gain par image)", fill=(0, 0, 0), font=f_t)
    dr.text((marge, 54), "Colonne de gauche : export Phocus.  Colonne de droite : 3FR rendu par notre profil.", fill=(70, 70, 70), font=f_m)
    y = tete
    for nom, g, ip, inn, med in lignes:
        for col, (img_, lib) in enumerate(((ip, "Phocus"), (inn, "Notre profil HNCS"))):
            x = marge + col * (wi + marge)
            dr.text((x, y), f"{lib}  -  {nom}", fill=(0, 0, 0), font=f_m)
            im.paste(Image.fromarray(img_), (x, y + 28))
        dr.text((marge + wi + marge + 330, y), f"gain {g:+.2f} IL, ΔE2000 médiane {med:.2f} (image entière)", fill=(70, 70, 70), font=f_m)
        y += hi + 60
    im.save(chemin)


def rapport_md(res, pr_h, pr_a, D, fit_img, held_img, depuis_etat, bilan, wb=None):
    n = D.n_img
    L = []
    mset = lambda de, imgs: de[np.isin(D.img, imgs)]
    L.append("# Ajustement du profil HNCS (chemin n°1), X2D II\n")
    L.append("Produit par `tools/ajuster.py` (une commande refait tout). DCP : `profiles/Hasselblad X2D II HNCS.dcp`. "
             "Tous les ΔE2000 ci-dessous sont calculés avec `chaine_adobe.rendre_xyz_d50` **sur le DCP relu**, "
             "avec un gain d'exposition libre par image (recherche 1D, perte de Huber), pour Adobe Standard comme pour HNCS. "
             "Référence principale : export Phocus (HNCS) ; contrôle : JPEG du boîtier (gains réajustés contre le JPEG, profil inchangé).\n")
    L.append(f"- 33 images, 124 414 blocs uniformes (≤ 4 000 par image). **Ajustement** : {len(fit_img)} images ; "
             f"**tenue à part** : {len(held_img)} images (indice ≡ 3 mod 4 : "
             + ", ".join(D.noms[i] for i in held_img) + "), dont seul le gain est ajusté.")
    L.append("- Avertissement d'honnêteté : ce sont des ΔE du modèle (chaîne de référence du SDK DNG, sans noir automatique), "
             "pas un rendu Lightroom réel ; le vrai test reste Lightroom sur 3FR (voir Limites).\n")
    L.append("## Paramètres retenus\n")
    E = res["E"]
    L.append(f"- ColorMatrix1/2 et illuminants (A / D65) : ceux d'Adobe, inchangés. UniqueCameraModel `{NOM_CAMERA}`.")
    L.append("- ForwardMatrix1/2 = M · FM Adobe, avec M (blanc D50 fixe, neutre intact) =")
    M = matrice_M(E)
    L.append("  `" + "  ".join("[" + " ".join(f"{v:+.4f}" for v in r) + "]" for r in M) + "`")
    L.append(f"- ProfileToneCurve : {len(res['pts'])} points (x, y), spline d'Adobe, monotone sur 4097 points :")
    L.append("  `" + " ".join(f"({x:.3f},{y:.4f})" for x, y in res["pts"]) + "`")
    L.append(f"- LookTable {LOOK_DIMS[0]}x{LOOK_DIMS[1]}x{LOOK_DIMS[2]} (teinte x saturation x valeur, encodage sRGB), "
             f"lissage {res['lam']} (choisi par validation interne sur 6 images d'ajustement), saturation 0 strictement neutre, "
             "aucune HueSatMap ; DefaultBlackRender = 1 (aucun noir automatique).")
    L.append(f"- BaselineExposureOffset = {res['offset']:+.3f} IL (médiane résiduelle des gains des images d'ajustement ; "
             "équivaut à un gain ajouté à toutes les images).")
    L.append("- BaselineExposure du 3FR (`exiftool`) : **0** ; `Baseline Exposure Offset` lu dans le 3FR : -0,02 (c'est un tag de "
             "profil, ignoré ici). Ce qu'Adobe Camera Raw applique réellement aux 3FR X2D II est **inconnu** : on suppose 0 "
             "(`exposition_base=0` dans `chaine_adobe`). Une valeur différente décale tous les gains du même nombre d'IL.\n")
    L.append("## ΔE2000 : Adobe Standard contre HNCS\n")
    L.append("| Référence | Groupe | Profil | médiane | 90e centile |\n|---|---|---|---|---|")
    for ref, nomref in (("t", "Phocus"), ("j", "JPEG")):
        for grp, imgs in (("ajustement", fit_img), ("tenue à part", held_img)):
            for nomp, key in (("Adobe Standard", "a"), ("HNCS", "h")):
                de = mset(bilan[(key, ref)][1], imgs)
                m, p = stats(de)
                L.append(f"| {nomref} | {grp} ({len(imgs)} images) | {nomp} | {m:.2f} | {p:.2f} |")
    L.append("\nPour mémoire, l'écart Phocus / JPEG du boîtier (measurements/phocus-vs-jpeg.md) : médiane 1,97 brut, 1,25 après gain par image.\n")
    L.append("## Gains d'exposition par image (IL, contre Phocus ; > 0 = plus clair que le profil à 0 IL)\n")
    ga, gh = bilan[("a", "t")][0], bilan[("h", "t")][0]
    L.append("| Image | groupe | blocs | gain Adobe Std | gain HNCS | ΔE méd. Adobe | ΔE méd. HNCS | ΔE 90e HNCS | ΔE méd. HNCS vs JPEG |\n|---|---|---|---|---|---|---|---|---|")
    for i in range(n):
        s = D.sl[i]
        grp = "tenue à part" if i in held_img else "ajustement"
        da, dh_, dj = bilan[("a", "t")][1][s], bilan[("h", "t")][1][s], bilan[("h", "j")][1][s]
        L.append(f"| {D.noms[i]} | {grp} | {s.stop - s.start} | {ga[i]:+.2f} | {gh[i]:+.2f} | {np.median(da):.2f} | "
                 f"{np.median(dh_):.2f} | {np.percentile(dh_, 90):.2f} | {np.median(dj):.2f} |")
    L.append(f"\nGain médian HNCS : {np.median(gh):+.3f} IL (toutes images), {np.median(gh[fit_img]):+.3f} IL (ajustement), "
             f"{np.median(gh[held_img]):+.3f} IL (tenue à part) ; gain médian Adobe Standard : {np.median(ga):+.3f} IL. "
             f"Écart-type des gains HNCS : {np.std(gh):.3f} IL (Phocus règle la luminosité photo par photo).\n")
    if wb is not None:
        p, rwb, (t0, t1) = wb
        L.append("## Balance des blancs : ce que le profil ne peut pas porter\n")
        L.append("Diagnostic : avec un profil sans réglage de balance, les quasi-neutres de Phocus sortaient plus chauds que ceux de la chaîne Adobe "
                 "(b* +1 à +1,6 en médiane, mesuré sur un premier ajustement trop lissé), et un décalage de balance propre à chaque image "
                 "faisait passer la médiane de 2,16 à 1,73 : Phocus n'utilise pas exactement la balance « as shot » du 3FR, image par image. "
                 "Un profil ne peut pas porter cela (Adobe renormalise la ForwardMatrix pour que le neutre reste neutre, la LookTable laisse les gris intacts). "
                 f"Avec le profil final, un décalage global constant du CameraNeutral (R x{1 + p[0]:.4f}, B x{1 + p[1]:.4f}, ajusté sur les images d'ajustement) n'apporte plus que peu :\n")
        L.append("| Groupe | sans décalage (médiane / 90e) | avec décalage (médiane / 90e) |\n|---|---|---|")
        for k, (a, b) in rwb.items():
            L.append(f"| {k} | {a[0]:.2f} / {a[1]:.2f} | {b[0]:.2f} / {b[1]:.2f} |")
        L.append(f"\nÉquivalent en curseurs Lightroom : balance médiane des 33 images {t0[0]:.0f} K, teinte {t0[1]:+.1f} -> "
                 f"{t1[0]:.0f} K, teinte {t1[1]:+.1f} (en unités Adobe ; le sens, plus chaud, compte plus que la valeur exacte). "
                 "À tester dans Lightroom : régler la température un peu plus haut que « tel quel » après application du profil.\n")
    L.append("## Fichiers\n")
    L.append("- Figure : `measurements/ajustement-courbes-teintes.png` (rampe de gris Adobe Standard / HNCS avec les blocs neutres de Phocus, bandes de teintes avant/après).")
    L.append("- Planche : `measurements/planche-tenue-a-part.png` (4 images tenues à part, Phocus | notre profil).\n")
    L.append("## Limites\n")
    L.append("- Ces ΔE sont ceux de la chaîne de référence du SDK DNG (vérifiée à < 0,06 ΔE contre dcamprof), pas ceux de Lightroom Classic, "
             "dont le moteur de rendu (traitement de version 6+, noir automatique, courbe de tonalité propre, etc.) n'est pas public. "
             "DefaultBlackRender = 1 est écrit pour s'en rapprocher, sans garantie.")
    L.append("- La HueSatMap d'Adobe (bi-illuminant, interpolée en 1/T selon la balance) est retirée : le profil n'est validé que sur les "
             "températures des 33 images (voir ci-dessous) ; hors de cette plage, seule la ForwardMatrix interpolée entre A et D65 joue.")
    L.append("- Gain par image : HNCS règle la luminosité photo par photo (écart-type des gains ci-dessus) ; un profil fixe ne le fait pas, il se compense à l'exposition dans Lightroom.")
    L.append("- Données : blocs uniformes du centre des images (hors blocs écrêtés), 33 images de juillet 2026 : peu de très hautes lumières, de ciels saturés et de couleurs très saturées ; ces zones sont extrapolées par le lissage et le rappel vers le neutre.")
    L.append("- HDR de Phocus non couvert. `UniqueCameraModel` : le 3FR porte « Hasselblad X2D II 100C » alors que le profil Adobe (et celui-ci) porte « " + NOM_CAMERA + " » ; si le profil n'apparaît pas dans Lightroom, c'est le premier suspect.")
    L.append(f"- Plage de balances des 33 images : {D_temp_plage(D)}.")
    L.append("- Le gain médian est ramené à ~0 IL pendant l'ajustement ; le résidu est dans BaselineExposureOffset.")
    L.append("- Reproduire : `python3 tools/ajuster.py` ; contrôle : `python3 tools/ajuster.py --self-test`.")
    pathlib.Path(MD_SORTIE).write_text("\n".join(L) + "\n", encoding="utf-8")


def D_temp_plage(D):
    base = Base().p
    t = [ca.xy_vers_temp(xy)[0] for xy in D.xy(base)]
    return f"{min(t):.0f} K à {max(t):.0f} K (médiane {np.median(t):.0f} K)"


# ============================================================ programme
def principal(args):
    TMP.mkdir(parents=True, exist_ok=True)
    D = charger_donnees()
    fit_img = np.array([i for i in range(D.n_img) if i % 4 != 3])
    held_img = np.array([i for i in range(D.n_img) if i % 4 == 3])
    etat = TMP / "etat.npz"
    if args.depuis_etat and etat.exists():
        z = np.load(etat)
        res = dict(E=z["E"], pts=z["pts"], look=z["look"], offset=float(z["offset"]), lam=float(z["lam"]), base=Base())
    else:
        print("ajustement (alternance gains/courbe/FM/LookTable) ...")
        res = ajuster(D, fit_img, log=print)
        np.savez(etat, E=res["E"], pts=res["pts"], look=res["look"], offset=res["offset"], lam=res["lam"])
    print("écriture du DCP et relecture ...")
    pr_h = ecrire_dcp(res, DCP_SORTIE)
    pr_a = ca.charger_dcp(ca.DCP_ADOBE)
    print("évaluation (chaîne officielle, DCP relu) ...")
    bilan = {}
    for key, pr in (("a", pr_a), ("h", pr_h)):
        for ref in ("t", "j"):
            bilan[(key, ref)] = evaluer(D, pr, ref)
            print(f"  profil {key}, réf {ref} : médiane {np.median(bilan[(key, ref)][1]):.3f}")
    print("décalage de balance (diagnostic) ...")
    wb = decalage_wb(D, pr_h, bilan[("h", "t")][0], fit_img, held_img)
    rapport_md(res, pr_h, pr_a, D, fit_img, held_img, args.depuis_etat, bilan, wb)
    gh = bilan[("h", "t")][0]
    figure(res, pr_h, pr_a, D, gh, FIG_SORTIE)
    if not args.sans_planche:
        print("planche (décodage de 4 3FR) ...")
        planche(pr_h, gh, D, PLANCHE_SORTIE)
    print("terminé :", DCP_SORTIE)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--sans-planche", action="store_true")
    ap.add_argument("--depuis-etat", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    for _d in ("measurements", "profiles"):
        (PROJET / _d).mkdir(exist_ok=True)   # output folders, created on first real run
    return principal(a)


if __name__ == "__main__":
    sys.exit(main())
