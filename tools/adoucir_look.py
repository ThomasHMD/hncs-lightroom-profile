#!/usr/bin/env python3
"""Adoucit la LookTable d'un profil HNCS pour supprimer le banding des dégradés qui passent près du neutre.

Cause (19/11/2026, ciel de coucher de soleil envoyé par un utilisateur, XCD 35-100E, ISO 50) : dans les faibles
saturations (nœud s = 0,14 de la table 36 x 8 x 8), la LookTable de « HNCS » varie fortement d'une case de teinte
à la voisine (décalage de teinte de -14° à +31°, facteur de saturation de 0,8 à 1,7). Un ciel pâle qui passe du bleu
au jaune traverse le neutre : sa teinte balaie tout le cercle en quelques pixels, et chaque case donne une couleur
différente -> bandes roses et vertes. Prouvé dans Camera Raw réel : sans LookTable, ou avec les nœuds de faible
saturation ramenés au neutre, le banding retombe au niveau d'Adobe Standard ; le facteur de valeur n'y est pour rien.

Correctif : lissage circulaire en teinte, d'autant plus fort que la saturation est faible, et rapprochement du
neutre des nœuds de faible saturation (à moitié en s1, au quart en s2 : ramener tout au neutre effaçait le
réchauffement des gris chauds que fait HNCS). HNCS 1.2 ajoute `hautes_lumieres` (anneaux autour des soleils,
voir sa docstring). Les tables restent celles de l'ajustement ailleurs.

  adoucir_look.py ecrire <HNCS 1.0.dcp> <sortie.dcp> --nom "HNCS" [--sigma 2.0] [--neutre 0.5] [--sans-hl]   # défauts = HNCS 1.2
  adoucir_look.py essai-synthetique <profil.dcp> ...     # énergie de cassure sur des dégradés qui traversent le neutre
  adoucir_look.py balayage <profil.dcp>                   # réglages contre fidélité (modèle) ; il faut le dossier de travail (3FR de la passe 1)
  adoucir_look.py --self-test
"""
import argparse
import copy
import pathlib
import sys

import numpy as np
from scipy.ndimage import gaussian_filter1d

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import chaine_adobe as ca  # noqa: E402
import dcp_ecrire  # noqa: E402

NEUTRE = np.array([0.0, 1.0, 1.0])


def adoucir(look, sigma=2.0, neutre=0.5, moyenne=0.0):
    """look (V,H,S,3) -> table adoucie.

    sigma : écart-type (en cases de teinte, 10° par case pour 36 teintes) du lissage circulaire au nœud s1 ;
            il décroît en 1/s ensuite (s1 : sigma, s2 : sigma/2, s3 : sigma/3…).
    neutre : part de rapprochement du neutre au nœud s1 (la moitié au nœud s2).
    moyenne : part de rapprochement, aux nœuds s1 et s2 (moitié en s2), de la moyenne sur toutes les teintes du
              même nœud (garde le caractère moyen près du neutre, retire ce qui varie d'une teinte à l'autre).
    Le nœud s = 0 reste neutre (exigé par la spec pour les gris).
    """
    V, H, S, _ = look.shape
    out = look.copy()
    for s in range(1, S):
        sg = sigma / s
        if sg > 0.05:
            out[:, :, s] = gaussian_filter1d(look[:, :, s], sg, axis=1, mode="wrap")
    if moyenne:
        wm = np.zeros(S)
        wm[1:3] = [moyenne, moyenne / 2]
        moy = out.mean(axis=1, keepdims=True)
        out = out * (1 - wm)[None, None, :, None] + moy * wm[None, None, :, None]
    w = np.zeros(S)
    w[1:3] = [neutre, neutre / 2]
    out = out * (1 - w)[None, None, :, None] + NEUTRE * w[None, None, :, None]
    out[:, :, 0] = NEUTRE
    return out


def hautes_lumieres(look):
    """HNCS 1.2 : le dernier plan de valeur (v = 1, les pixels les plus clairs) reprend le plan précédent, puis la
    valeur de sortie (v x facteur de valeur) est rendue croissante le long de v pour chaque (teinte, saturation).

    Cause (19/11/2026, soleils couchants) : au plan v = 1, l'ajustement avait mis un facteur de valeur de 0,47 et
    de saturation de 1,6 pour les jaunes-orangés à s = 0,43 (sans doute des cases sans données : les blocs presque
    blancs sont rares et souvent écrêtés). En s'approchant du soleil, le ciel s'assombrissait avant de repasser au
    blanc : un anneau autour du soleil, absent d'Adobe Standard et du HEIC du boîtier.
    """
    V = look.shape[0]
    out = look.copy()
    out[V - 1] = out[V - 2]
    vn = np.arange(V) / (V - 1)
    for k in range(1, V):
        plancher = out[k - 1, ..., 2] * vn[k - 1] / vn[k]     # même valeur de sortie qu'au plan précédent
        out[k, ..., 2] = np.maximum(out[k, ..., 2], plancher)
    return out


def valeur_monotone(look):
    """Nombre de pas où la valeur de sortie redescend quand la valeur d'entrée monte (0 attendu)."""
    V = look.shape[0]
    sortie = look[..., 2] * (np.arange(V) / (V - 1))[:, None, None]
    return int((np.diff(sortie, axis=0) < -1e-6).sum())


def degrades_synthetiques(n=600):
    """Dégradés ProPhoto linéaires entre couleurs opposées, qui passent tout près du neutre (ciels, peau/ombre…)."""
    paires = [((0.20, 0.28, 0.45), (0.55, 0.47, 0.32)),   # ciel bleu -> horizon jaune
              ((0.30, 0.34, 0.40), (0.42, 0.38, 0.33)),   # ciel pâle -> brume chaude
              ((0.40, 0.30, 0.35), (0.30, 0.38, 0.33)),   # rose -> vert
              ((0.35, 0.36, 0.30), (0.30, 0.31, 0.42)),   # jaune-vert -> bleu-violet
              ((0.08, 0.10, 0.16), (0.16, 0.13, 0.09))]   # même chose dans les ombres
    t = np.linspace(0, 1, n)[:, None]
    return [np.asarray(a) * (1 - t) + np.asarray(b) * t for a, b in paires]


def _lab_prophoto(rgb):
    xyz = rgb @ ca.PROPHOTO_VERS_XYZ_D50.T if hasattr(ca, "PROPHOTO_VERS_XYZ_D50") else rgb @ np.array(
        [[0.7977, 0.1352, 0.0313], [0.2880, 0.7119, 0.0001], [0, 0, 0.8249]]).T
    w = np.array([0.9642, 1, 0.8249])
    f = lambda x: np.where(x > 0.008856, np.cbrt(x), 7.787 * x + 16 / 116)  # noqa: E731
    fx, fy, fz = [f(xyz[..., i] / w[i]) for i in range(3)]
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], -1)


def energie_cassure(look, encodage=1):
    """Somme sur les dégradés de max |d²a*| + |d²b*| + |d²L*| (par pas de 1/600) après LookTable seule.

    Un dégradé lisse donne une petite valeur ; une table qui casse d'une case à l'autre la fait monter.
    """
    tot = 0.0
    for g in degrades_synthetiques():
        out = g if look is None else ca.appliquer_table_hsv(g, look, encodage)
        lab = _lab_prophoto(out)
        d2 = np.abs(np.diff(lab, 2, axis=0)) * len(g) ** 2 / 1e4
        tot += float(d2.max(0).sum())
    return tot


def lire_look(chemin):
    p = dcp_ecrire.lire(str(chemin))
    if "ProfileLookTableDims" not in p:
        return p, None
    H, S, V = p["ProfileLookTableDims"]
    return p, np.array(p["ProfileLookTableData"], float).reshape(V, H, S, 3)


def ecrire(entree, sortie, nom, sigma, neutre, hl=True):
    p, look = lire_look(entree)
    q = copy.deepcopy(p)
    q["ProfileName"] = nom
    t = adoucir(look, sigma, neutre)
    q["ProfileLookTableData"] = (hautes_lumieres(t) if hl else t).reshape(-1).tolist()
    dcp_ecrire.ecrire(str(sortie), q)
    return q


def fidelite(profils, sans_gain=False):
    """ΔE2000 médiane / 90e (modèle chaine_adobe, cible Phocus) sur les images tenues à part de la passe 2.

    Le modèle s'écarte de Camera Raw (~1,6 ΔE, mesures/passe2.md) : on lit l'ÉCART entre profils, pas l'absolu.
    """
    import ajuster_v2 as V2
    V2.dims_phocus = lambda nom, passe: (11656, 8742)        # exports Phocus effacés ; seule la géométrie en dépend
    D = V2.charger_v2()
    _, held = V2.decouper(D)
    base = V2.expo_base(D, {})
    out = {}
    for cle, prof in profils.items():
        _, de = V2.evaluer_v2(D, prof, base, images=held, sans_gain=sans_gain)
        ok = ~np.isnan(de)
        faible = ok & (np.hypot(D.lab_t[:, 1], D.lab_t[:, 2]) < 12)        # blocs peu saturés (gris chauds, ciels pâles)
        out[cle] = (float(np.median(de[ok])), float(np.percentile(de[ok], 90)), float(np.median(de[faible])))
    return out


def self_test():
    rng = np.random.default_rng(0)
    look = np.tile(NEUTRE, (8, 36, 8, 1)).astype(float)
    assert np.allclose(adoucir(look), look), "une table neutre doit rester neutre"
    nerveuse = look.copy()
    nerveuse[:, :, 1:, 0] += rng.normal(0, 15, nerveuse[:, :, 1:, 0].shape)
    nerveuse[:, :, 1:, 1] *= np.exp(rng.normal(0, 0.3, nerveuse[:, :, 1:, 1].shape))
    e0, e1 = energie_cassure(nerveuse), energie_cassure(adoucir(nerveuse))
    eid = energie_cassure(None)
    assert e1 < e0 * 0.6, f"l'adoucissement doit réduire la cassure ({e0:.2f} -> {e1:.2f})"
    assert np.allclose(adoucir(nerveuse)[:, :, 0], NEUTRE), "nœud s = 0 neutre"
    # garde-fou permanent : le profil livré ne doit pas casser les dégradés qui traversent le neutre
    racine = pathlib.Path(__file__).resolve().parents[1]
    t_hl = hautes_lumieres(nerveuse)
    assert valeur_monotone(t_hl) == 0, "hautes_lumieres doit rendre la valeur de sortie croissante"
    for livre in (racine / "profils" / "Hasselblad X2D II HNCS 1.2.dcp", racine / "release" / "HNCS-Hasselblad-X2D-II.dcp"):
        if not livre.exists():
            continue
        _, lk = lire_look(livre)
        el = energie_cassure(lk)
        assert el < 20, f"profil livré : cassure {el:.2f} >= 20 (banding probable ; HNCS 1.0 : 33,8)"
        nm = valeur_monotone(lk)
        assert nm == 0, f"profil livré : la luminosité redescend à {nm} endroits quand l'entrée monte (anneaux autour des soleils)"
        print(f"  profil livré {livre.name} : cassure {el:.2f} (< 20), valeur de sortie croissante")
    print(f"self-test OK (adoucir_look) : cassure sans table {eid:.2f}, table bruitée {e0:.2f}, adoucie {e1:.2f}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["ecrire", "essai-synthetique", "balayage"])
    ap.add_argument("fichiers", nargs="*")
    ap.add_argument("--nom", default="HNCS")
    ap.add_argument("--sigma", type=float, default=2.0)
    ap.add_argument("--neutre", type=float, default=0.5)
    ap.add_argument("--sans-hl", action="store_true", help="sans la correction des hautes lumières (= HNCS 1.1)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.action == "ecrire":
        ecrire(a.fichiers[0], a.fichiers[1], a.nom, a.sigma, a.neutre, hl=not a.sans_hl)
        print("écrit", a.fichiers[1])
    elif a.action == "balayage":
        p, look = lire_look(a.fichiers[0])
        enc = p["ProfileLookTableEncoding"][0]
        prof0 = ca.charger_dcp_dict(p)
        grille = [(0, 0, 0), (2, 1.0, 0), (2, 0, 1.0), (2, 0.3, 0.7), (4, 0, 1.0), (2, 0.5, 0.5), (3, 0.3, 1.0)]
        profils = {}
        for sg, nt, mo in grille:
            q = copy.deepcopy(prof0)
            q.look = adoucir(look, sg, nt, mo) if (sg or nt or mo) else look
            profils[(sg, nt, mo)] = q
        fid = fidelite(profils)
        for k, q in profils.items():
            m, p90, mf = fid[k]
            print(f"sigma {k[0]:.1f} neutre {k[1]:.1f} moyenne {k[2]:.1f} : cassure {energie_cassure(q.look, enc):6.2f}"
                  f"  ΔE méd {m:.3f}  90e {p90:.3f}  faible chroma {mf:.3f}", flush=True)
    elif a.action == "essai-synthetique":
        print(f"sans table : {energie_cassure(None):.2f}")
        for f in a.fichiers:
            p, look = lire_look(f)
            enc = p.get("ProfileLookTableEncoding", [1])[0]
            print(f"{p['ProfileName']} : {energie_cassure(look, enc):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
