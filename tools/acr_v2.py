#!/usr/bin/env python3
"""Rendus Camera Raw réels pour la passe 2 (Photoshop piloté en JSX, comme `valider_acr.py` qu'on importe).

Pour une liste d'images (noms de 3FR de la passe 1 ou 2) et une liste de profils (nom Camera Raw -> étiquette) :
copie du 3FR dans le chantier, sidecar XMP (ProcessVersion 11.0, profil imposé, balance « As Shot », tout à 0,
Exposure2012 = 0 : Camera Raw applique seul la BaselineExposure du 3FR), ouverture par Photoshop, TIFF 16 bits ProPhoto,
moyennes de blocs de 16 px aux positions des blocs de `ajuster_v2.charger_v2`, version réduite au 1/8 (option), TIFF
effacé.  Photoshop est quitté à la fin s'il n'était pas ouvert au départ ; Lightroom n'est jamais lancé.

  acr_v2.py rendre --profils "HNCS v2 t0=t0" --images B0000583 ... [--reduite B0000583 ...]
  acr_v2.py --self-test
"""
import argparse
import pathlib
import shutil
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import echantillons as E  # noqa: E402
import valider_acr as VA  # noqa: E402
import ajuster_v2 as V2  # noqa: E402

C = E.C
TMP = C / "tmp-acr-v2"
RES = TMP / "res"
VA.TMP = TMP            # valider_acr écrit son script JSX dans VA.TMP
VA.RES = RES            # cache des références Phocus réduites (ref_reduite)


def chemin_res(nom, cle):
    return RES / f"{nom}__{cle}.npz"


def entree(D, i):
    return (C / ("phocus-entree" if D.passe[i] == 1 else "phocus-entree-2")) / f"{D.noms[i]}.3FR"


def preparer_geometrie(D, i):
    VA.SORTIE = C / ("phocus-sortie" if D.passe[i] == 1 else "phocus-sortie-2")


def rendre(D, noms, profils, refaire=False, reduite=()):
    """profils : dict cle -> nom de profil Camera Raw.  Un rendu = un npz (enc aux blocs de D, décalage, [red])."""
    RES.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    for nom in noms:
        i = D.noms.index(nom)
        todo = [c for c in profils if refaire or not chemin_res(nom, c).exists()]
        if not todo:
            continue
        raw = TMP / f"{nom}.3FR"
        shutil.copyfile(entree(D, i), raw)
        s = D.sl[i]
        by, bx = D.by[s], D.bx[s]
        preparer_geometrie(D, i)
        try:
            for cle in todo:
                t = time.time()
                tif = TMP / f"rendu_{nom}_{cle.replace(' ', '_')}.tif"
                (TMP / f"{nom}.xmp").write_text(VA.xmp(profils[cle], 0.0))
                if tif.exists():
                    tif.unlink()
                info = VA.ps(VA.JSX_RENDU % {"raw": raw, "tif": tif})
                assert tif.exists(), "TIFF non écrit"
                d, bm, red = VA.lire_blocs(tif)
                m, g = VA.verifier_icc_prophoto(d)
                decal, note = VA.etat_geometrie(nom, red)
                kw = dict(enc=bm[by, bx], by=by, bx=bx, icc_gamma=g, icc_colorants=m, info=info,
                          decalage_px=np.array(decal if decal else (-9999, -9999)), note_geom=note,
                          dims=np.array([d["h"], d["w"]]), profil=profils[cle])
                if nom in reduite:
                    kw["red"] = red
                np.savez(chemin_res(nom, cle), **kw)
                tif.unlink()
                print(f"{nom} [{cle}] : {info} ; décalage {decal} {note} ; {time.time() - t:.0f}s", flush=True)
        finally:
            raw.unlink(missing_ok=True)
            (TMP / f"{nom}.xmp").unlink(missing_ok=True)


def xyz_rendu(nom, cle):
    """XYZ D50 du rendu Camera Raw aux blocs enregistrés (+ by, bx)."""
    r = np.load(chemin_res(nom, cle))
    return VA.decode_prophoto(r["enc"].astype(np.float64), r["icc_colorants"], float(r["icc_gamma"])), r["by"], r["bx"]


def self_test():
    # xmp et JSX : ce qu'on envoie à Photoshop est bien formé
    t = VA.xmp("HNCS v2 t0", 0.0)
    d = VA.lire_xmp(t)
    assert d["CameraProfile"] == "HNCS v2 t0" and d["Exposure2012"] == "+0.00" and d["LensProfileEnable"] == "0"
    D = V2.charger_v2()
    assert D.n_img > 100 and set(D.passe) == {1, 2}
    i = D.noms.index("B0000583")
    assert chemin_res("x", "y").parent == RES
    if not entree(D, i).parent.exists():
        print("  (3FR folder absent: the check that the raw files exist is skipped)")
    else:
        assert entree(D, i).exists()
    assert V2.geometrie_ok(D, i)
    print("self-test OK (acr_v2) :", D.n_img, "images,", len(D.cam), "blocs")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["rendre"])
    ap.add_argument("--profils", nargs="*", help="cle=Nom du profil Camera Raw")
    ap.add_argument("--images", nargs="*")
    ap.add_argument("--reduite", nargs="*", default=[])
    ap.add_argument("--refaire", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.action == "rendre":
        D = V2.charger_v2()
        profils = dict(p.split("=", 1) for p in a.profils)
        avant = VA.ps_ouvert()
        try:
            rendre(D, a.images, profils, a.refaire, set(a.reduite))
        finally:
            if not avant:
                VA.ps_quitter()
    return 0


if __name__ == "__main__":
    sys.exit(main())
