#!/usr/bin/env python3
"""Chef d'orchestre de la passe 2 du profil HNCS (voir `measurements/passe2.md`).

  passe2.py donnees                 # images retenues / exclues par objectif x ISO x lumière, ajustement / tenue à part
  passe2.py modele-v1               # le profil v1 dans le modèle avec BE par image : repère les images aberrantes
  passe2.py tour0                   # ajustement sans correction Camera Raw -> t0
  passe2.py rendre N                # rendus Camera Raw du profil tN (sous-ensemble d'ajustement S + validation V)
  passe2.py corriger N              # epsilon mesuré sur les rendus de tN -> ajustement corrigé t(N+1)
  passe2.py mesurer N               # ΔE Camera Raw de tN sur S et V
  passe2.py sans-objectif "XCD 38V" # tenue à part par objectif entier (modèle)
  passe2.py par-objectif            # profil par objectif : gain potentiel (modèle, mêmes blocs tenus à part)
  passe2.py choisir N               # installe la version N comme « HNCS v2 » (DCP final + copie dans Camera Raw)
  passe2.py final                   # rendus tenue à part (v1, v2, Adobe Standard) et passe2.md + planche-v2.png
  passe2.py --self-test

Les profils intermédiaires vivent dans CameraProfiles/_hncs-v2-tmp/ (retirés en fin de travail, ce dossier seulement).
Lightroom n'est jamais lancé ; Photoshop est quitté après chaque série de rendus s'il n'était pas ouvert.
"""
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "6")

import argparse
import json
import pathlib
import shutil
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ajuster as A  # noqa: E402
import ajuster_v2 as V2  # noqa: E402
import acr_v2 as ACR  # noqa: E402
import chaine_adobe as ca  # noqa: E402
import valider_acr as VA  # noqa: E402

PROJET = A.PROJET
C = A.C
TMP = V2.TMP2
PROFDIR = pathlib.Path.home() / "Library/Application Support/Adobe/CameraRaw/CameraProfiles"
PROFTMP = PROFDIR / "_hncs-v2-tmp"
DCP_V1 = PROJET / "profiles" / "Hasselblad X2D II HNCS.dcp"   # v1, written by ajuster.py
FINAL_NOM = "HNCS v2"
N_S, N_V = 24, 12


def de(a, b):
    return A.de2000(A.xyz_lab(a), A.xyz_lab(b))


# ============================================================ sous-ensembles à rendre
def _fps(F, deja, n, rng):
    """Échantillonnage du point le plus éloigné dans l'espace des caractéristiques F (lignes)."""
    choisis = list(deja)
    if not choisis:
        choisis = [int(rng.integers(len(F)))]
    d = np.min(np.linalg.norm(F[:, None, :] - F[choisis][None], axis=-1), axis=1)
    while len(choisis) < n:
        k = int(np.argmax(d))
        choisis.append(k)
        d = np.minimum(d, np.linalg.norm(F - F[k], axis=1))
    return choisis


def caracteristiques(D):
    obj = sorted(set(D.obj))
    return np.column_stack([[3.0 * obj.index(o) for o in D.obj], np.log2(D.iso) / 2.0, np.clip(D.temp, 2500, 8000) / 2000.0,
                            D.be * 1.5, (D.passe == 1) * 0.5])


def sous_ensembles(D, fit, held):
    rng = np.random.default_rng(0)
    F = caracteristiques(D)
    gf = [i for i in fit if V2.geometrie_ok(D, i)]
    S = [gf[k] for k in _fps(F[gf], [], N_S, rng)]
    gh = [i for i in held if V2.geometrie_ok(D, i)]
    forces = []
    for ob in sorted(set(D.obj[gh])):                       # un par objectif
        forces.append(max((i for i in gh if D.obj[i] == ob), key=lambda i: D.iso[i] * 0 + len(D.cam[D.sl[i]])))
    forces.append(max(gh, key=lambda i: D.iso[i]))          # le plus haut ISO
    chauds = sorted(gh, key=lambda i: D.temp[i])[:2]        # les plus chauds
    forces += chauds
    forces += [i for i in gh if D.be[i] >= 0.5][:2]
    forces = list(dict.fromkeys(forces))
    pos = {i: k for k, i in enumerate(gh)}
    V = [gh[k] for k in _fps(F[gh], [pos[i] for i in forces], max(N_V, len(forces)), rng)]
    return [D.noms[i] for i in S], [D.noms[i] for i in V], [D.noms[i] for i in gh]


# ============================================================ état partagé (cmap, étapes)
def etat_json():
    f = TMP / "etat.json"
    return json.loads(f.read_text()) if f.exists() else {}


def sauver_json(d):
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "etat.json").write_text(json.dumps(d, indent=1))


def cmap_de(e, n):
    """c(BE) utilisé pour l'ajustement du tour n : mesuré aux tours précédents (n-1), sinon passe 1."""
    return {int(k): v for k, v in e.get("cmap", {}).get(str(n), {}).items()}


def dernier_cmap(e):
    c = e.get("cmap", {})
    return {int(k): v for k, v in c[max(c, key=int)].items()} if c else {}


def installer_dcp(res, nom):
    PROFTMP.mkdir(parents=True, exist_ok=True)
    chemin = PROFTMP / f"{nom}.dcp"
    pr = V2.ecrire_dcp_v2(res, chemin, nom)
    return pr, chemin


def profil_depuis_etat(n):
    res = V2.charger_etat(TMP / f"etat_t{n}.npz")
    return res, ca.charger_dcp(PROFTMP / f"HNCS v2 t{n}.dcp")


# ============================================================ commandes : données
def cmd_donnees(D, fit, held):
    isoc = lambda x: "≤200" if x <= 200 else ("400-1600" if x <= 1600 else "≥3200")
    lignes = ["objectif | groupe | ISO | chaud<4500K | images | blocs"]
    from collections import Counter
    cnt = Counter()
    for i in range(D.n_img):
        g = "tenue" if i in set(held) else "ajust."
        cnt[(D.obj[i], g, isoc(D.iso[i]), bool(D.temp[i] < 4500))] += 1
    for k, v in sorted(cnt.items()):
        print(k, v)
    print("exclues (< %d blocs à CV <= %.2f) : %s" % (V2.MIN_BLOCS, V2.CV_FIT, D.exclues))
    print("images", D.n_img, "blocs", len(D.cam), "ajustement", len(fit), "tenue à part", len(held))
    print("noms en double :", len(D.noms) - len(set(D.noms)))
    print("géométrie hors 11656x8742 :", [(D.noms[i], tuple(D.dims[i])) for i in range(D.n_img) if not V2.geometrie_ok(D, i)])


def cmd_modele_v1(D, fit, held):
    """v1 (profil installé) dans le modèle avec BE + c(BE) par image, sur la passe 2 : médiane de ΔE par image, aberrantes."""
    pr = ca.charger_dcp(DCP_V1)
    cmap = {}
    base = V2.expo_base(D, cmap)
    gains, de_ = V2.evaluer_v2(D, pr, base)
    med = np.array([np.median(de_[s]) if s.stop > s.start else np.nan for s in D.sl])
    print("ΔE2000 médiane par image (profil v1, BE + c(BE), gain libre borné), pires 15 :")
    for i in np.argsort(-med)[:15]:
        print(f"  {D.noms[i]} {D.obj[i]} ISO {D.iso[i]} {D.temp[i]:.0f}K BE {D.be[i]:.2f} : {med[i]:.2f} ; gain {gains[i]:+.2f} ; blocs {D.sl[i].stop - D.sl[i].start}")
    print("médiane globale", np.median(de_[~np.isnan(de_)]), "gain médian", np.median(gains))


# ============================================================ tour 0 et corrections
def lancer_ajustement(D, fit, n, ecrire=True):
    e = etat_json()
    cmap = cmap_de(e, n)
    base = V2.expo_base(D, cmap)
    Dfit = D
    if n > 0:
        prev, prof_prev = profil_depuis_etat(n - 1)
        eps = np.load(TMP / f"eps_t{n - 1}.npz")
        eps_fn = V2.Epsilon(eps["lab_m"], eps["eps"], eps["be_cl"])
        base_prev = V2.expo_base(D, cmap_de(e, n - 1))
        # exposition totale du modèle au tour précédent : BE + c + gain - offset (l'offset est déjà dans le DCP)
        gains_tot = base_prev - D.be + prev["gains"] - prev["offset"]
        tgt, lab_m, ee = V2.cible_corrigee(D, prof_prev, D.be, gains_tot, eps_fn)
        print(f"cible corrigée : |ε| médian {np.median(np.linalg.norm(ee, axis=1)):.2f} (Lab)")
        Dfit = D.avec_cible(tgt)
    init = None
    if (TMP / "etat_t0.npz").exists() and n > 0:
        init = V2.charger_etat(TMP / f"etat_t{n - 1}.npz")
    elif (A.TMP / "etat.npz").exists():
        z = np.load(A.TMP / "etat.npz")
        init = dict(E=z["E"], pts=z["pts"])
    t = time.time()
    res = V2.ajuster_v2(Dfit, fit, base, init=init)
    print(f"ajustement t{n} : {time.time() - t:.0f} s ; offset {res['offset']:+.3f}")
    V2.sauver_etat(res, TMP / f"etat_t{n}.npz")
    if ecrire:
        installer_dcp(res, f"HNCS v2 t{n}")
    return res


def cmd_tour0(D, fit, held):
    TMP.mkdir(parents=True, exist_ok=True)
    lancer_ajustement(D, fit, 0)


def cmd_corriger(D, fit, held, n):
    """epsilon et c(BE) mesurés sur les rendus Camera Raw de tN (images S), puis ajustement t(N+1)."""
    e = etat_json()
    S = e["S"]
    res, prof = profil_depuis_etat(n)
    cle = f"t{n}"
    labm, eps, bec, gstar = [], [], [], {}
    for nom in S:
        i = D.noms.index(nom)
        s = D.sl[i]
        xyz_cr, by, bx = ACR.xyz_rendu(nom, cle)
        assert np.array_equal(by, D.by[s]) and np.array_equal(bx, D.bx[s])
        g = meilleur_gain_modele(D, i, prof, xyz_cr)
        gstar[nom] = g
        xyz_m = ca.rendre_xyz_d50(D.cam[s], D.neutres[i], prof, g, exposition_base=D.be[i])
        lm = A.xyz_lab(xyz_m)
        sel = np.random.default_rng(i).choice(len(lm), min(len(lm), 1500), replace=False)
        labm.append(lm[sel])
        eps.append((A.xyz_lab(xyz_cr) - lm)[sel])
        bec.append(np.full(len(sel), np.clip(np.round(D.be[i]), 0, 2)))
    np.savez(TMP / f"eps_t{n}.npz", lab_m=np.concatenate(labm), eps=np.concatenate(eps), be_cl=np.concatenate(bec))
    cm = {}
    for k in (0, 1, 2):
        v = [gstar[nm] for nm in S if np.clip(np.round(D.be[D.noms.index(nm)]), 0, 2) == k]
        if v:
            cm[k] = float(np.median(v))
    e.setdefault("cmap", {})[str(n + 1)] = cm
    e.setdefault("gstar", {})[str(n)] = gstar
    sauver_json(e)
    allE = np.concatenate(eps)
    print(f"c(BE) mesuré au tour {n} : {cm} ; ε moyen (Lab) {allE.mean(0).round(2)}, |ε| médian {np.median(np.linalg.norm(allE, axis=1)):.2f}")
    lancer_ajustement(D, fit, n + 1)


def meilleur_gain_modele(D, i, prof, xyz_cr, lo=-1.0, hi=1.0):
    from scipy.optimize import minimize_scalar
    s = D.sl[i]
    f = lambda g: float(np.median(de(ca.rendre_xyz_d50(D.cam[s], D.neutres[i], prof, g, exposition_base=D.be[i]), xyz_cr)))
    grille = np.arange(lo, hi + 1e-9, 0.2)
    g0 = grille[int(np.argmin([f(g) for g in grille]))]
    return float(minimize_scalar(f, bounds=(g0 - 0.2, g0 + 0.2), method="bounded", options={"xatol": 1e-3}).x)


# ============================================================ rendus et mesures Camera Raw
def cmd_rendre(D, fit, held, n):
    e = etat_json()
    if "S" not in e:
        S, V, H = sous_ensembles(D, fit, held)
        e.update(S=S, V=V, H=H)
        sauver_json(e)
    noms = e["S"] + e["V"]
    avant = VA.ps_ouvert()
    try:
        ACR.rendre(D, noms, {f"t{n}": f"HNCS v2 t{n}"})
    finally:
        if not avant:
            VA.ps_quitter()


def stat(a):
    a = np.concatenate(a) if len(a) else np.array([np.nan])
    return float(np.median(a)), float(np.percentile(a, 90))


def mesure_cr(D, nom, cle):
    """ΔE2000 Camera Raw contre Phocus : sans gain, avec gain libre post-rendu (borné +-0,8 IL) ; + gain."""
    i = D.noms.index(nom)
    s = D.sl[i]
    xyz, by, bx = ACR.xyz_rendu(nom, cle)
    assert np.array_equal(by, D.by[s]) and np.array_equal(bx, D.bx[s]), nom
    ref = D.tgt[s]
    g = VA.meilleur_gain_post(xyz, ref, lo=-0.8, hi=0.8)
    return dict(sans=de(xyz, ref), avec=de(xyz * 2.0 ** g, ref), gain=g, xyz=xyz)


def cmd_mesurer(D, fit, held, n, quiet=False):
    e = etat_json()
    out = {}
    for grp in ("S", "V"):
        r = [mesure_cr(D, nm, f"t{n}") for nm in e[grp]]
        a, b = stat([x["avec"] for x in r]), stat([x["sans"] for x in r])
        out[grp] = (a, b, float(np.median([x["gain"] for x in r])))
        if not quiet:
            print(f"t{n} Camera Raw, {grp} ({len(r)} images) : avec gain libre {a[0]:.2f} / {a[1]:.2f} ; sans gain {b[0]:.2f} / {b[1]:.2f} ; gain médian {out[grp][2]:+.3f}")
    e.setdefault("measurements", {})[str(n)] = {g: [list(v[0]), list(v[1]), v[2]] for g, v in out.items()}
    sauver_json(e)
    return out


# ============================================================ tenue à part par objectif, profil par objectif (modèle)
def cmd_sans_objectif(D, fit, held, objectif):
    cmap = {}   # mêmes conditions que le tour 0 (sans correction Camera Raw) : comparaison à l'ajustement global t0
    base = V2.expo_base(D, cmap)
    out = [i for i in range(D.n_img) if D.obj[i] == objectif]
    fit_sans = np.array([i for i in fit if D.obj[i] != objectif])
    print(f"{objectif} : {len(out)} images mises de côté ; ajustement sur {len(fit_sans)} images")
    res = V2.ajuster_v2(D, fit_sans, base)
    pr = A.profil_depuis(res["base"], res["E"], res["pts"], res["look"], res["offset"])
    glob = V2.charger_etat(TMP / "etat_t0.npz")
    pr_glob = A.profil_depuis(glob["base"], glob["E"], glob["pts"], glob["look"], glob["offset"])
    rows = {}
    for nom, p in (("sans " + objectif, pr), ("avec (profil global t0, même modèle)", pr_glob)):
        g, d_ = V2.evaluer_v2(D, p, base, images=out)
        rows[nom] = d_[np.concatenate([np.arange(D.sl[i].start, D.sl[i].stop) for i in out])]
        print(f"  {nom} : ΔE2000 modèle médiane {np.median(rows[nom]):.2f} / 90e {np.percentile(rows[nom], 90):.2f}")
    TMP.mkdir(exist_ok=True)
    (TMP / f"sans_{objectif.replace(' ', '_')}.json").write_text(json.dumps(
        {k: [float(np.median(v)), float(np.percentile(v, 90))] for k, v in rows.items()}))


def cmd_par_objectif(D, fit, held):
    e = etat_json()
    base = V2.expo_base(D, {})   # mêmes conditions que le tour 0
    glob = V2.charger_etat(TMP / "etat_t0.npz")
    pr_glob = A.profil_depuis(glob["base"], glob["E"], glob["pts"], glob["look"], glob["offset"])
    res_all = {}
    for ob in sorted(set(D.obj)):
        fit_o = np.array([i for i in fit if D.obj[i] == ob])
        held_o = [i for i in held if D.obj[i] == ob]
        if len(fit_o) < 4 or len(held_o) < 2:
            print(f"{ob} : trop peu d'images ({len(fit_o)} ajustement, {len(held_o)} tenue à part), ignoré")
            continue
        res = V2.ajuster_v2(D, fit_o, base, lams=(0.02, 0.08), n_sub=700)
        pr = A.profil_depuis(res["base"], res["E"], res["pts"], res["look"], res["offset"])
        idx = np.concatenate([np.arange(D.sl[i].start, D.sl[i].stop) for i in held_o])
        r = {}
        for nom, p in (("profil de l'objectif", pr), ("profil global", pr_glob)):
            g, d_ = V2.evaluer_v2(D, p, base, images=held_o)
            r[nom] = (float(np.median(d_[idx])), float(np.percentile(d_[idx], 90)), float(np.median([g[i] for i in held_o])))
        res_all[ob] = dict(r=r, n_fit=len(fit_o), n_held=len(held_o))
        print(ob, res_all[ob], flush=True)
    (TMP / "par_objectif.json").write_text(json.dumps(res_all, indent=1))


# ============================================================ choix, rendu final, rapport
PROFILS_FINAL = {"v1": "HNCS", "v2": FINAL_NOM, "adobe": "Adobe Standard"}
ETIQ = {"v1": "HNCS v1", "v2": "HNCS v2", "adobe": "Adobe Standard"}


def cmd_choisir(D, fit, held, n):
    res = V2.charger_etat(TMP / f"etat_t{n}.npz")
    V2.ecrire_dcp_v2(res, V2.DCP_V2, FINAL_NOM)
    shutil.copyfile(V2.DCP_V2, PROFDIR / V2.DCP_V2.name)
    e = etat_json()
    e["final"] = n
    sauver_json(e)
    print("DCP final :", V2.DCP_V2, "-> copié dans", PROFDIR)


def planche_noms(D, V):
    ids = [D.noms.index(n) for n in V]
    pick = []
    for crit in (lambda i: D.obj[i] == "XCD 38V", lambda i: D.obj[i] == "XCD 35-100E", lambda i: D.obj[i] == "XCD 55V"):
        c = [i for i in ids if crit(i) and i not in pick]
        if c:
            pick.append(c[0])
    for key in (lambda i: -D.iso[i], lambda i: D.temp[i], lambda i: -D.be[i]):
        c = sorted([i for i in ids if i not in pick], key=key)
        if c and len(pick) < 6:
            pick.append(c[0])
    for i in ids:
        if len(pick) < 6 and i not in pick:
            pick.append(i)
    return [D.noms[i] for i in pick[:6]]


def cmd_final_rendre(D, fit, held):
    e = etat_json()
    H = e["H"]
    red = planche_noms(D, e["V"])
    e["planche"] = red
    sauver_json(e)
    avant = VA.ps_ouvert()
    try:
        ACR.rendre(D, H, dict(PROFILS_FINAL), reduite=set(red))
    finally:
        if not avant:
            VA.ps_quitter()


def _isoc(x):
    return "ISO ≤ 200" if x <= 200 else ("ISO 400 à 1600" if x <= 1600 else "ISO ≥ 3200")


def cmd_rapport(D, fit, held):
    e = etat_json()
    H = e["H"]
    cles = list(PROFILS_FINAL)
    R = {c: {n: mesure_cr(D, n, c) for n in H} for c in cles}
    idx = {n: D.noms.index(n) for n in H}
    hl = {n: D.tgt[D.sl[idx[n]]][:, 1] > 0.6 for n in H}

    def tab(groupe, titre, key="avec"):
        L = [f"| {titre} | images | " + " | ".join(f"{ETIQ[c]} méd. / 90e" for c in cles) + " |", "|---|---|" + "---|" * len(cles)]
        for nom, ns in groupe:
            if not ns:
                continue
            cells = []
            for c in cles:
                m, p = stat([R[c][n][key] for n in ns])
                cells.append(f"{m:.2f} / {p:.2f}")
            L.append(f"| {nom} | {len(ns)} | " + " | ".join(cells) + " |")
        return L

    def hl_tab(key):
        cells = []
        for c in cles:
            a = [R[c][n][key][hl[n]] for n in H if hl[n].any()]
            m, p = stat(a)
            cells.append(f"{m:.2f} / {p:.2f}")
        nb = sum(int(hl[n].sum()) for n in H)
        return f"| blocs Phocus Y > 0,6 ({nb} blocs) | {len([n for n in H if hl[n].any()])} | " + " | ".join(cells) + " |"

    tout = [("toutes les images tenues à part", H)]
    objs = [(o, [n for n in H if D.obj[idx[n]] == o]) for o in sorted(set(D.obj))]
    isos = [(k, [n for n in H if _isoc(D.iso[idx[n]]) == k]) for k in ("ISO ≤ 200", "ISO 400 à 1600", "ISO ≥ 3200")]
    chaud = [("lumière chaude < 4500 K", [n for n in H if D.temp[idx[n]] < 4500]), ("autres (≥ 4500 K)", [n for n in H if D.temp[idx[n]] >= 4500])]
    be = [("BaselineExposure 0", [n for n in H if D.be[idx[n]] < 0.5]), ("BaselineExposure ≥ 1", [n for n in H if D.be[idx[n]] >= 0.5])]
    md = ["# Passe 2 : profil HNCS v2 mesuré dans Camera Raw", "",
          "Produit par `tools/passe2.py` (`donnees`, `tour0`, `rendre N`, `corriger N`, `choisir N`, `final`). Tous les ΔE2000 de ce fichier sont "
          "mesurés sur de **vrais rendus Camera Raw** (Photoshop piloté en JSX, `acr_v2.py`, sidecar XMP : profil imposé, tout à 0, "
          "Exposure2012 = 0, balance As Shot, corrections d'objectif off), contre l'export Phocus SDR, par blocs uniformes de 16 px "
          "(CV <= 0,08, couronne centrale). Lightroom n'a pas été lancé. « Avec gain » = un gain libre par image (curseur d'exposition, "
          "borné ±0,8 IL) ; « sans gain » = Camera Raw tel quel.", ""]
    md += ["## Données", "", e.get("texte_donnees", ""), ""]
    md += ["## Tenue à part, Camera Raw réel : v1 / v2 / Adobe Standard", "",
           f"{len(H)} images tenues à part (1 sur 4 stratifiée par objectif, hors images à géométrie Phocus recadrée), jamais utilisées pour l'ajustement ni pour la correction par Camera Raw (les 12 images V ont servi à choisir entre les tours).", "",
           "### Avec gain libre par image", ""]
    md += tab(tout + objs + [("- ISO", [])] + isos + chaud + be, "Groupe")[:2] + tab(tout, "Groupe")[2:]
    md += tab(objs, "Objectif")[2:] + tab(isos, "ISO")[2:] + tab(chaud, "Lumière")[2:] + tab(be, "BE")[2:] + [hl_tab("avec")]
    md += ["", "### Sans gain (Camera Raw en l'état, exposition 0)", ""]
    md += tab(tout, "Groupe", "sans")[:2] + tab(tout, "Groupe", "sans")[2:] + tab(objs, "Objectif", "sans")[2:] + tab(isos, "ISO", "sans")[2:] + tab(chaud, "Lumière", "sans")[2:] + tab(be, "BE", "sans")[2:] + [hl_tab("sans")]
    # gain résiduel par objectif
    md += ["", "### Gain résiduel (IL) pour coller à Phocus, HNCS v2, par objectif et par BaselineExposure", "",
           "| Objectif | images | gain médian | min | max |", "|---|---|---|---|---|"]
    for o, ns in objs:
        g = [R["v2"][n]["gain"] for n in ns]
        md.append(f"| {o} | {len(ns)} | {np.median(g):+.2f} | {min(g):+.2f} | {max(g):+.2f} |")
    for nom, ns in be:
        g = [R["v2"][n]["gain"] for n in ns]
        if g:
            md.append(f"| {nom} | {len(ns)} | {np.median(g):+.2f} | {min(g):+.2f} | {max(g):+.2f} |")
    md += ["", "## Tours de correction par Camera Raw", "",
           "| Tour | S (ajustement, avec gain) | V (tenue à part, avec gain) | V sans gain | gain médian V |", "|---|---|---|---|---|"]
    for k, m in sorted(e.get("measurements", {}).items(), key=lambda x: int(x[0])):
        md.append(f"| t{k}{' (retenu)' if int(k) == e.get('final', -1) else ''} | {m['S'][0][0]:.2f} / {m['S'][0][1]:.2f} | {m['V'][0][0]:.2f} / {m['V'][0][1]:.2f} | {m['V'][1][0]:.2f} / {m['V'][1][1]:.2f} | {m['V'][2]:+.3f} |")
    md += ["", e.get("texte_tours", "")]
    for f, titre in (("par_objectif.json", "Profil par objectif : gain potentiel (modèle)"),):
        if (TMP / f).exists():
            d = json.loads((TMP / f).read_text())
            md += ["", f"## {titre}", "", "Mêmes blocs tenus à part, même modèle (`chaine_adobe`, BE + c(BE)) ; ΔE2000 médiane / 90e / gain médian (IL).", "",
                   "| Objectif | images ajustement | images tenues | profil de l'objectif | profil global | gain de ΔE médiane |", "|---|---|---|---|---|---|"]
            for o, v in d.items():
                a, b = v["r"]["profil de l'objectif"], v["r"]["profil global"]
                md.append(f"| {o} | {v['n_fit']} | {v['n_held']} | {a[0]:.2f} / {a[1]:.2f} | {b[0]:.2f} / {b[1]:.2f} | {b[0] - a[0]:+.2f} |")
    for p in sorted(TMP.glob("sans_*.json")):
        d = json.loads(p.read_text())
        md += ["", f"## Tenue à part par objectif entier : {p.stem[5:].replace('_', ' ')} (modèle)", ""]
        for k, v in d.items():
            md.append(f"- {k} : ΔE2000 médiane {v[0]:.2f} / 90e {v[1]:.2f}")
    md += ["", e.get("texte_conclusion", "")]
    (PROJET / "measurements" / "passe2.md").write_text("\n".join(md) + "\n")
    print("passe2.md écrit")
    planche_v2(D, e, R)


def planche_v2(D, e, R):
    from PIL import Image, ImageDraw, ImageFont
    noms = e.get("planche", [])
    W = 520
    pol = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    pet = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 17)
    lignes = []
    for nom in noms:
        i = D.noms.index(nom)
        VA.SORTIE = C / ("phocus-sortie" if D.passe[i] == 1 else "phocus-sortie-2")
        rp = VA.ref_reduite(nom)
        cols = [VA_srgb(E_decode_adobe(rp.astype(np.float32) / 65535))]
        for c in ("v2", "adobe"):
            r = np.load(ACR.chemin_res(nom, c))
            cols.append(VA_srgb(VA.decode_prophoto(r["red"].astype(np.float32) / 65535, r["icc_colorants"], float(r["icc_gamma"]))))
        lignes.append((nom, cols))
    haut = [int(W * c[0].shape[0] / c[0].shape[1]) for _, c in lignes]
    marge, bandeau, leg = 8, 48, 26
    H_ = bandeau + sum(h + leg + marge for h in haut) + marge
    img = Image.new("RGB", (3 * W + 4 * marge, H_), (24, 24, 24))
    dr = ImageDraw.Draw(img)
    for k, t in enumerate(("Phocus (HNCS)", "Camera Raw + HNCS v2", "Camera Raw + Adobe Standard")):
        dr.text((marge + k * (W + marge), 12), t, fill=(255, 255, 255), font=pol)
    y = bandeau
    for (nom, cols), h in zip(lignes, haut):
        i = D.noms.index(nom)
        for k, a in enumerate(cols):
            img.paste(Image.fromarray(a).resize((W, h), Image.LANCZOS), (marge + k * (W + marge), y))
        m2, ma = np.median(R["v2"][nom]["avec"]), np.median(R["adobe"][nom]["avec"])
        dr.text((marge, y + h + 4), f"{nom}  {D.obj[i]}  ISO {D.iso[i]}  {D.temp[i]:.0f} K  BE {D.be[i]:+.1f} : ΔE médiane HNCS v2 {m2:.2f}, Adobe Standard {ma:.2f} (Camera Raw exposition 0, gain libre)", fill=(200, 200, 200), font=pet)
        y += h + leg + marge
    out = PROJET / "measurements" / "planche-v2.png"
    img.save(out)
    print("planche :", out, img.size)


def VA_srgb(xyz):
    return VA._srgb_depuis_xyz(xyz)


def E_decode_adobe(v):
    import echantillons as E
    return E.decode_adobe(v)


def self_test():
    D = V2.charger_v2()
    fit, held = V2.decouper(D)
    assert len(set(fit) & set(held)) == 0 and len(fit) + len(held) == D.n_img
    S, V, H = sous_ensembles(D, fit, held)
    assert len(S) == N_S and len(V) >= N_V - 0 and set(V) <= set(H) and not set(S) & set(H)
    assert all(V2.geometrie_ok(D, D.noms.index(n)) for n in S + V)
    # epsilon -> cible : ε nul laisse la cible Phocus intacte
    fn = V2.Epsilon(np.random.default_rng(0).uniform([10, -20, -20], [90, 20, 20], (500, 3)), np.zeros((500, 3)), np.zeros(500))
    tgt, lm, ee = V2.cible_corrigee(D.vue(np.arange(2000)), ca.charger_dcp(DCP_V1), np.zeros(D.n_img), np.zeros(D.n_img), fn)
    assert np.abs(tgt - D.tgt[:2000]).max() < 1e-9
    assert not (PROFTMP.exists() and any(PROFTMP.glob("Hasselblad*")))
    print("self-test OK (passe2) :", len(S), "S,", len(V), "V,", len(H), "tenue à part rendable")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    for _d in ("measurements", "profiles"):
        (PROJET / _d).mkdir(exist_ok=True)   # output folders, created on first real run
    D = V2.charger_v2()
    fit, held = V2.decouper(D)
    act = a.action
    if act == "donnees":
        cmd_donnees(D, fit, held)
    elif act == "modele-v1":
        cmd_modele_v1(D, fit, held)
    elif act == "tour0":
        cmd_tour0(D, fit, held)
    elif act == "rendre":
        cmd_rendre(D, fit, held, int(a.arg))
    elif act == "corriger":
        cmd_corriger(D, fit, held, int(a.arg))
    elif act == "mesurer":
        cmd_mesurer(D, fit, held, int(a.arg))
    elif act == "sans-objectif":
        cmd_sans_objectif(D, fit, held, a.arg)
    elif act == "choisir":
        cmd_choisir(D, fit, held, int(a.arg))
    elif act == "final-rendre":
        cmd_final_rendre(D, fit, held)
    elif act == "rapport":
        cmd_rapport(D, fit, held)
    elif act == "par-objectif":
        cmd_par_objectif(D, fit, held)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
