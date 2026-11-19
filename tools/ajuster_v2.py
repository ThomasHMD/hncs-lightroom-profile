#!/usr/bin/env python3
"""Passe 2 de l'ajustement du profil HNCS : 33 + 148 images, BaselineExposure par image, correction par Camera Raw réel.

Réutilise `ajuster.py` (importé, inchangé) pour tout ce qui est ajustement (courbe, ForwardMatrix, LookTable en HSV,
ΔE2000) ; ce module ajoute :

  - les données : `samples-pass1.npz` (passe 1) + `samples-pass2.npz` (passe 2), référence Phocus seule,
    blocs de texture CV <= 0,08 ; méta par image (objectif, focale, ISO, BaselineExposure, température) ;
  - la BaselineExposure du 3FR comme exposition de base propre à chaque image (Camera Raw l'applique seul : c'est la
    luminosité automatique de HNCS), plus l'écart constant « Camera Raw - modèle » c(BE) mesuré sur les rendus réels ;
    le gain résiduel libre par image est borné (+-0,8 IL) ;
  - la tenue à part : 1 image sur 4, stratifiée par objectif (passe 1 : les 8 mêmes qu'en passe 1) ; et une tenue à part
    par objectif entier (`--sans-objectif "XCD 38V"`) ;
  - la correction d'après Camera Raw : à partir des rendus Camera Raw d'un sous-ensemble (voir `acr_v2.py`), l'écart
    systématique epsilon = Camera Raw - modèle (en Lab, par bloc) est prédit pour toutes les images par une régression
    de plus proches voisins sur (L*, a*, b*, classe de BE) ; la cible d'ajustement devient Phocus - epsilon, et on
    réajuste courbe, ForwardMatrix et LookTable (lissées) : Camera Raw doit alors retrouver Phocus ;
  - l'écriture du DCP (ProfileName « HNCS v2 »).

  ajuster_v2.py ajuster --tour 0                  # ajustement sans correction (tour 0), écrit profils intermédiaires
  ajuster_v2.py ajuster --tour N                  # avec epsilon mesuré au tour N-1 (rendus de acr_v2.py)
  ajuster_v2.py sans-objectif "XCD 38V"           # tenue à part par objectif (modèle seul)
  ajuster_v2.py --self-test
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "6")

import argparse
import json
import pathlib
import subprocess
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ajuster as A  # noqa: E402
import chaine_adobe as ca  # noqa: E402
import dcp_ecrire  # noqa: E402
import echantillons as E  # noqa: E402

PROJET = A.PROJET
C = A.C
NPZ1 = PROJET / "data" / "samples-pass1.npz"
NPZ2 = PROJET / "data" / "samples-pass2.npz"
TMP2 = C / "tmp-ajuster-v2"
DCP_V2 = PROJET / "profiles" / "Hasselblad X2D II HNCS v2.dcp"
CV_FIT = 0.08
MIN_BLOCS = 300
BORNE_GAIN = 0.8
TENUES_PASSE1 = ["B0000586", "B0000590", "B0000594", "B0000601", "B0000607", "B0000612", "B0000616", "B0000710"]
# écart Camera Raw - modèle (IL) par classe de BaselineExposure arrondie, mesuré en passe 1 (validation-acr.md) ;
# remplacé par la mesure de la passe 2 dès qu'il y a des rendus
C_BE_PASSE1 = {0: -0.15, 1: 0.10, 2: 0.09}


# ============================================================ données
class DonneesV2(A.Donnees):
    """A.Donnees + méta par image (be, obj, iso, foc, temp, passe) et par bloc (cv, by, bx)."""
    EXTRA_BLOC = ("cv", "by", "bx")
    EXTRA_IMG = ("be", "obj", "iso", "foc", "temp", "passe", "dims")

    def vue(self, idx):
        d = DonneesV2.__new__(DonneesV2)
        d.cam, d.tgt, d.img = self.cam[idx], self.tgt[idx], self.img[idx]
        d.jpg = None
        d.neutres, d.n_img, d.noms = self.neutres, self.n_img, self.noms
        d.lab_t = self.lab_t[idx]
        d.lab_j = None
        b = np.searchsorted(d.img, np.arange(d.n_img + 1))
        d.sl = [slice(b[i], b[i + 1]) for i in range(d.n_img)]
        d._xy = self._xy
        for k in self.EXTRA_BLOC:
            if hasattr(self, k):
                setattr(d, k, getattr(self, k)[idx])
        for k in self.EXTRA_IMG:
            if hasattr(self, k):
                setattr(d, k, getattr(self, k))
        return d

    def avec_cible(self, tgt_xyz):
        """Copie dont la cible (Phocus) est remplacée (cible corrigée de epsilon)."""
        d = self.vue(np.arange(len(self.cam)))
        d.tgt = tgt_xyz
        d.lab_t = A.xyz_lab(tgt_xyz)
        return d


def meta_passe1(noms, z1=None):
    """Métadonnées de la passe 1 : lues dans data/samples-pass1.npz ; sinon (anciens fichiers) dans les 3FR via exiftool."""
    if z1 is not None and "objectif" in z1.files:
        ix = {str(n): i for i, n in enumerate(z1["noms"])}
        return {n: dict(objectif=str(z1["objectif"][ix[n]]), iso=int(z1["iso"][ix[n]]),
                        be=float(z1["baseline_exposure"][ix[n]]), focale=float(z1["focale"][ix[n]])) for n in noms}
    f = TMP2 / "meta_passe1.json"
    if f.exists():
        d = json.loads(f.read_text())
        if all(n in d for n in noms):
            return {n: d[n] for n in noms}
    TMP2.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["exiftool", "-json", "-n", "-LensModel", "-ISO", "-BaselineExposure", "-FocalLength"]
                       + [str(C / "phocus-entree" / f"{n}.3FR") for n in noms], capture_output=True, text=True, check=True)
    d = {n: dict(objectif=e["LensModel"], iso=int(e["ISO"]), be=float(e.get("BaselineExposure", 0.0)),
                 focale=float(e.get("FocalLength", 0))) for n, e in zip(noms, json.loads(r.stdout))}
    f.write_text(json.dumps(d))
    return d


def dims_phocus(nom, passe, z=None):
    """(largeur, hauteur) de l'export Phocus : lues dans le npz de la passe si présentes, sinon dans le TIFF."""
    if z is not None and "image_width" in z.files:
        i = [str(n) for n in z["noms"]].index(nom)
        return (int(z["image_width"][i]), int(z["image_height"][i]))
    d = E.lire_tiff((C / ("phocus-sortie" if passe == 1 else "phocus-sortie-2")) / f"B_{nom[-4:]}.tif")
    return (d["w"], d["h"])


def charger_v2(cv_fit=CV_FIT):
    z1 = np.load(NPZ1, allow_pickle=True)
    z2 = np.load(NPZ2, allow_pickle=True)
    n1, n2 = len(z1["noms"]), len(z2["noms"])
    noms = [str(x) for x in z1["noms"]] + [str(x) for x in z2["noms"]]
    cam = np.concatenate([z1["cam_rgb"], z2["cam_rgb"]]).astype(float)
    tgt = np.concatenate([z1["phocus_xyz"], z2["phocus_xyz"]]).astype(float)
    img = np.concatenate([z1["image"].astype(int), z2["image"].astype(int) + n1])
    cv = np.concatenate([np.zeros(len(z1["image"])),
                         np.maximum(z2["cv_raw"].astype(float), z2["cv_phocus"].astype(float))])
    by = np.concatenate([z1["by"], z2["by"]]).astype(int)
    bx = np.concatenate([z1["bx"], z2["bx"]]).astype(int)
    wb = np.concatenate([z1["wb_as_shot"], z2["wb_as_shot"]]).astype(float)
    m1 = meta_passe1(noms[:n1], z1)
    obj = [m1[n]["objectif"] for n in noms[:n1]] + [str(x) for x in z2["objectif"]]
    iso = [m1[n]["iso"] for n in noms[:n1]] + [int(x) for x in z2["iso"]]
    foc = [m1[n]["focale"] for n in noms[:n1]] + [float(x) for x in z2["focale"]]
    be = [m1[n]["be"] for n in noms[:n1]] + [float(x) for x in z2["baseline_exposure"]]
    passe = [1] * n1 + [2] * n2
    keep = cv <= cv_fit
    nb = np.bincount(img[keep], minlength=n1 + n2)
    ok_img = nb >= MIN_BLOCS
    remap = -np.ones(n1 + n2, int)
    remap[ok_img] = np.arange(ok_img.sum())
    keep &= ok_img[img]
    sel = np.flatnonzero(ok_img)
    neutres = np.stack([1 / wb[sel, 0], np.ones(len(sel)), 1 / wb[sel, 2]], -1)
    d = DonneesV2(cam[keep], tgt[keep], None, remap[img[keep]], neutres, [noms[i] for i in sel])
    d.cv, d.by, d.bx = cv[keep], by[keep], bx[keep]
    d.be = np.array(be)[sel]
    d.obj = np.array(obj)[sel]
    d.iso = np.array(iso)[sel]
    d.foc = np.array(foc)[sel]
    d.passe = np.array(passe)[sel]
    d.dims = np.array([dims_phocus(noms[i], passe[i], (z1, z2)[passe[i] - 1]) for i in sel])
    base = A.Base().p
    d.temp = np.array([ca.xy_vers_temp(xy)[0] for xy in d.xy(base)])
    d.exclues = [noms[i] for i in np.flatnonzero(~ok_img)]
    return d


def decouper(D):
    """(ajustement, tenue à part) : passe 1 = les 8 de la passe 1 ; passe 2 = 1 image sur 4 par objectif (rang 3 mod 4)."""
    held = set()
    for i, n in enumerate(D.noms):
        if D.passe[i] == 1 and n in TENUES_PASSE1:
            held.add(i)
    for ob in sorted(set(D.obj[D.passe == 2])):
        ids = sorted([i for i in range(D.n_img) if D.passe[i] == 2 and D.obj[i] == ob], key=lambda i: D.noms[i])
        held.update(ids[k] for k in range(len(ids)) if k % 4 == 3)
    held = np.array(sorted(held))
    fit = np.array([i for i in range(D.n_img) if i not in set(held)])
    return fit, held


def geometrie_ok(D, i):
    """Rendu Camera Raw de même géométrie que l'export Phocus (pas de recadrage Phocus) : 11656 x 8742 ou 8742 x 11656."""
    return tuple(D.dims[i]) in ((11656, 8742), (8742, 11656))


# ============================================================ exposition de base par image
def c_be(be, cmap):
    """Écart Camera Raw - modèle (IL) pour une BaselineExposure : classe arrondie (0, 1, 2)."""
    k = int(np.clip(np.round(be), 0, 2))
    return float(cmap.get(k, C_BE_PASSE1[k]))


def expo_base(D, cmap):
    return np.array([D.be[i] + c_be(D.be[i], cmap) for i in range(D.n_img)])


# ============================================================ gains bornés (autour de la base)
def ajuster_gains_v2(D, rgb1, pts, look, gains, images, base, offset=0.0):
    g = gains.copy()
    lab = D.lab_t
    for i in images:
        s = D.sl[i]
        if s.stop == s.start:
            continue

        def f(x, s=s, i=i):
            e = base[i] + x + offset
            P = (lambda r: r if look is None else ca.appliquer_table_hsv(r, look, 1))(A.exposer(rgb1[s], e))
            out = ca._appliquer_tonalite(P, A.tab_tonalite(pts, e))
            return A.de2000(A.xyz_lab(A.xyz_depuis(out)), lab[s])
        g[i] = A.meilleur_gain(f, -BORNE_GAIN, BORNE_GAIN)
    return g


# ============================================================ ajustement
def ajuster_v2(D, fit_img, base, init=None, log=print, rapide=False, lams=(0.005, 0.02, 0.08), n_sub=700, graine=0):
    """Même enchaînement que ajuster.ajuster, avec exposition par image = base[i] + gain[i] (+ offset)."""
    t0 = time.time()
    bse = A.Base()
    rng = np.random.default_rng(graine)
    idx_fit = np.nonzero(np.isin(D.img, fit_img))[0]
    Df = D.vue(idx_fit)
    sel = []
    for i in fit_img:
        s = np.nonzero(Df.img == i)[0]
        if len(s):
            sel.append(np.sort(rng.choice(s, min(n_sub, len(s)), replace=False)))
    Ds = Df.vue(np.concatenate(sel))
    n = D.n_img
    E_ = np.zeros((3, 3)) if init is None else init["E"].copy()
    pts = np.stack([A.KNOTS, np.minimum(ca.courbe_acr3(A.KNOTS), 1.0)], -1) if init is None else init["pts"].copy()
    look = A.look_neutre()
    gains = np.zeros(n)
    k_iter = (1, 1) if rapide else (3, 2)
    maxit = 8 if rapide else 40

    def prof():
        return A.profil_depuis(bse, E_, pts, look)

    def expo():
        return base + gains

    def alt(nb, tag):
        nonlocal pts, gains
        r1 = A.etape1(Ds, prof())
        for _ in range(nb):
            gains = ajuster_gains_v2(Ds, r1, pts, look, gains, fit_img, base)
            gains[fit_img] -= np.median(gains[fit_img])
            P = A.post_look(Ds, r1, expo(), look)
            pts = A.ajuster_courbe(Ds, P, pts, expo(), maxiter=maxit)
        de = A.de_modele(Ds, (pts, look), r1, expo())
        log(f"  [{time.time() - t0:5.0f}s] {tag}: ΔE2000 médiane {np.median(de):.3f}, 90e {np.percentile(de, 90):.3f}")

    log("tour interne 0 : gains + courbe, sans LookTable")
    alt(k_iter[0], "gains/courbe")
    log("FM + courbe")
    E_, pts = A.ajuster_fm_courbe(Ds, bse, E_, pts, look, expo(), maxiter=4 if rapide else 25)
    alt(k_iter[1], "après FM")

    val = np.array([i for i in fit_img if i % 4 == 1])
    tr = np.array([i for i in fit_img if i % 4 != 1])
    lam_ch = None
    if len(val) and not rapide and len(lams) > 1:
        Dtr = Df.vue(np.nonzero(np.isin(Df.img, tr))[0])
        Dva = Df.vue(np.nonzero(np.isin(Df.img, val))[0])
        r1tr, r1va = A.etape1(Dtr, prof()), A.etape1(Dva, prof())
        w0 = A.poids_huber(Dtr, r1tr, pts, look, expo())
        res = {}
        for lm in lams:
            lk = A.ajuster_look(Dtr, r1tr, pts, expo(), w0, dict(h=lm, s=lm, v=lm, **{"0": lm / 10}))
            g = ajuster_gains_v2(Dva, r1va, pts, lk, gains, val, base)
            de = A.de_modele(Dva, (pts, lk), r1va, base + g)
            res[lm] = float(np.median(de)) + 0.25 * float(np.percentile(de, 90))
            log(f"  lissage {lm}: validation interne médiane+0,25·p90 = {res[lm]:.3f}")
        lam_ch = min(res, key=res.get)
    lm = lam_ch if lam_ch is not None else lams[min(1, len(lams) - 1)]
    lam = dict(h=lm, s=lm, v=lm, **{"0": lm / 10})
    log(f"lissage retenu : {lm}")

    for t in range(2 if rapide else 3):
        r1f = A.etape1(Df, prof())
        w = A.poids_huber(Df, r1f, pts, look, expo())
        look = A.ajuster_look(Df, r1f, pts, expo(), w, lam)
        alt(k_iter[1], f"tour {t + 1} : look + gains/courbe")
        if t == 1 and not rapide:
            E_, pts = A.ajuster_fm_courbe(Ds, bse, E_, pts, look, expo(), maxiter=20)
            alt(1, f"tour {t + 1} : FM+courbe avec look")
    r1f = A.etape1(Df, prof())
    w = A.poids_huber(Df, r1f, pts, look, expo())
    look = A.ajuster_look(Df, r1f, pts, expo(), w, lam)
    r1 = A.etape1(Ds, prof())
    gains = ajuster_gains_v2(Ds, r1, pts, look, gains, fit_img, base)
    offset = float(np.median(gains[fit_img]))
    log(f"  [{time.time() - t0:5.0f}s] médiane des gains finale {offset:+.3f} IL -> BaselineExposureOffset")
    return dict(E=E_, pts=pts, look=look, offset=offset, lam=lm, base=bse, gains=gains)


# ============================================================ DCP
def ecrire_dcp_v2(res, chemin, nom_profil="HNCS v2"):
    d = A.dcp_dict(res)
    d["ProfileName"] = nom_profil
    d["ProfileCopyright"] = "Thomas Hammoudi"
    chemin = pathlib.Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    dcp_ecrire.ecrire(str(chemin), d)
    return ca.charger_dcp(chemin)


def sauver_etat(res, chemin):
    np.savez(chemin, E=res["E"], pts=res["pts"], look=res["look"], offset=res["offset"], lam=res["lam"],
             gains=res.get("gains", np.zeros(0)))


def charger_etat(chemin):
    z = np.load(chemin)
    return dict(E=z["E"], pts=z["pts"], look=z["look"], offset=float(z["offset"]), lam=float(z["lam"]), base=A.Base(),
                gains=z["gains"] if "gains" in z.files else np.zeros(0))


# ============================================================ évaluation par le modèle
def evaluer_v2(D, profil, base, images=None, borne=BORNE_GAIN, sans_gain=False):
    """ΔE2000 modèle (Phocus) par bloc, gain libre par image borné autour de base (ou 0 si sans_gain)."""
    gains = np.zeros(D.n_img)
    de = np.full(len(D.cam), np.nan)
    for i, s in enumerate(D.sl):
        if s.stop == s.start or (images is not None and i not in set(images)):
            continue

        def f(g, s=s, i=i):
            xyz = ca.rendre_xyz_d50(D.cam[s], D.neutres[i], profil, g, exposition_base=base[i])
            return A.de2000(A.xyz_lab(xyz), D.lab_t[s])
        g = 0.0 if sans_gain else A.meilleur_gain(f, -borne, borne)
        gains[i] = g
        de[s] = f(g)
    return gains, de


# ============================================================ correction d'après Camera Raw
def lab_vers_xyz(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    inv = lambda f: np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27))
    return np.stack([inv(fx), inv(fy), inv(fz)], -1) * A.D50


class Epsilon:
    """epsilon = Lab(Camera Raw) - Lab(modèle) prédit par plus proches voisins sur (L*, a*, b*, classe de BE)."""
    PONDERATION_BE = 40.0

    def __init__(self, lab_m, eps, be_cl, k=80):
        from scipy.spatial import cKDTree
        self.k = k
        self.eps = eps
        self.tree = cKDTree(np.column_stack([lab_m, self.PONDERATION_BE * be_cl]))

    def __call__(self, lab_m, be_cl):
        d, j = self.tree.query(np.column_stack([lab_m, self.PONDERATION_BE * be_cl]), k=self.k)
        w = 1.0 / (d + 1.0)
        return (self.eps[j] * w[..., None]).sum(1) / w.sum(1, keepdims=True)


def cible_corrigee(D, profil, base, gains, eps_fn):
    """Phocus - epsilon(modèle) pour tous les blocs (XYZ). Le modèle est calculé avec le gain d'image `gains`."""
    lab_m = np.empty((len(D.cam), 3))
    for i, s in enumerate(D.sl):
        if s.stop == s.start:
            continue
        lab_m[s] = A.xyz_lab(ca.rendre_xyz_d50(D.cam[s], D.neutres[i], profil, gains[i], exposition_base=base[i]))
    be_cl = np.clip(np.round(D.be[D.img]), 0, 2)
    e = eps_fn(lab_m, be_cl)
    tgt = lab_vers_xyz(A.xyz_lab(D.tgt) - e)
    return tgt, lab_m, e


# ============================================================ self-test
def self_test():
    ok = True
    rng = np.random.default_rng(0)
    # 1) lab <-> xyz
    xyz = np.abs(rng.normal(0.3, 0.2, (500, 3))) * A.D50 + 1e-3
    assert np.abs(lab_vers_xyz(A.xyz_lab(xyz)) - xyz).max() < 1e-9
    # 2) epsilon : un décalage constant est retrouvé exactement
    lab_m = rng.uniform([10, -30, -30], [90, 30, 30], (4000, 3))
    eps = np.tile([0.5, -0.3, 0.2], (4000, 1))
    f = Epsilon(lab_m, eps, np.zeros(4000))
    q = f(lab_m[:50] + 0.1, np.zeros(50))
    assert np.abs(q - eps[:50]).max() < 1e-9
    # 3) donnees : filtre CV, découpage stratifié (rang 3 mod 4 par objectif), exposition de base
    cmap = {0: -0.1}
    assert abs(c_be(0.05, cmap) + 0.1) < 1e-12 and abs(c_be(1.2, cmap) - C_BE_PASSE1[1]) < 1e-12 and abs(c_be(2.4, {}) - C_BE_PASSE1[2]) < 1e-12
    D = DonneesV2(np.ones((6, 3)), np.ones((6, 3)), None, np.array([0, 0, 1, 1, 2, 2]), np.ones((3, 3)), ["B0000586", "B0000001", "B0000002"])
    D.cv, D.by, D.bx = np.zeros(6), np.arange(6), np.arange(6)
    D.be, D.obj, D.iso = np.zeros(3), np.array(["XCD 55V"] * 3), np.array([50] * 3)
    D.foc, D.temp, D.passe, D.dims = np.zeros(3), np.zeros(3), np.array([1, 2, 2]), np.zeros((3, 2))
    v = D.vue(np.array([0, 1, 2]))
    assert v.sl[0] == slice(0, 2) and v.sl[1] == slice(2, 3) and v.cv.shape == (3,)
    fit, held = decouper(D)
    assert list(held) == [0] and list(fit) == [1, 2]
    # 4) gains bornés : un gain vrai de +0,3 IL est retrouvé, un gain de 2 IL est borné à 0,8
    base = A.Base()
    prof = A.profil_depuis(base, np.zeros((3, 3)), np.stack([A.KNOTS, np.minimum(ca.courbe_acr3(A.KNOTS), 1.0)], -1), A.look_neutre())
    cam = np.abs(rng.normal(0.1, 0.05, (300, 3))) + 0.01
    neu = np.array([0.5, 1.0, 0.62])
    for vrai, att in ((0.3, 0.3), (2.0, BORNE_GAIN)):
        xyz = ca.rendre_xyz_d50(cam, neu, prof, vrai, exposition_base=0.5)
        Dm = DonneesV2(cam, xyz, None, np.zeros(300, int), neu[None, :], ["x"])
        r1 = A.etape1(Dm, prof)
        g = ajuster_gains_v2(Dm, r1, prof.courbe, None, np.zeros(1), [0], np.array([0.5]))
        assert abs(g[0] - att) < 0.06 or vrai > 1, (vrai, g)
        if vrai > 1:
            assert abs(g[0] - BORNE_GAIN) < 5e-3, g
    # 5) ajuster_v2 (rapide) sur données synthétiques : les gains vrais (autour de la base) sont retrouvés
    n_img, per = 4, 600
    neutres = np.stack([np.full(n_img, 0.55), np.ones(n_img), np.full(n_img, 0.62)], -1)
    cams, imgs = [], []
    for i in range(n_img):
        cams.append(np.abs(rng.normal(0.12, 0.08, (per, 3))) + 0.01)
        imgs.append(np.full(per, i))
    cam = np.concatenate(cams)
    img = np.concatenate(imgs)
    be = np.array([0.0, 1.0, 0.0, 2.0])
    vrais = np.array([0.1, -0.2, 0.05, 0.15])
    pts_v = np.stack([A.KNOTS, np.minimum(ca.courbe_acr3(A.KNOTS), 1.0)], -1)
    pv = A.profil_depuis(base, np.zeros((3, 3)), pts_v, A.look_neutre())
    tgt = np.concatenate([ca.rendre_xyz_d50(cam[img == i], neutres[i], pv, vrais[i], exposition_base=be[i]) for i in range(n_img)])
    Ds = DonneesV2(cam, tgt, None, img, neutres, [str(i) for i in range(n_img)])
    res = ajuster_v2(Ds, np.arange(n_img), be, log=lambda *a: None, rapide=True, n_sub=400)
    prof2 = A.profil_depuis(base, res["E"], res["pts"], res["look"], res["offset"])
    g, de = evaluer_v2(Ds, prof2, be)
    assert np.median(de) < 0.5, np.median(de)
    print("self-test OK (ajuster_v2) : ΔE médiane synthétique", round(float(np.median(de)), 3))
    # 6) l'ancien self-test d'ajuster.py passe toujours (rien n'a été modifié)
    assert A.self_test() == 0
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    for _d in ("measurements", "profiles"):
        (PROJET / _d).mkdir(exist_ok=True)   # output folders, created on first real run
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
