#!/usr/bin/env python3
"""Écrit (et relit) des profils caméra Adobe .dcp, structure TIFF « IIRC ».

    python3 dcp_ecrire.py --self-test          # aller-retour + exiftool, code 0 si tout passe
    python3 dcp_ecrire.py <profil.dcp>         # affiche les tags lus

    from dcp_ecrire import ecrire, lire
    ecrire("sortie.dcp", {"UniqueCameraModel": "...", "ProfileName": "...", ...})
    profil = lire("sortie.dcp")                # dict nom -> valeur (liste de nombres ou str)

Clés de `profil` (noms DNG ; un numéro de tag entier est accepté avec un tuple
(type, valeurs) pour les tags non listés) :
  UniqueCameraModel, ProfileName, ProfileCopyright, ProfileCalibrationSignature (ASCII)
  ColorMatrix1/2, ForwardMatrix1/2 : 9 nombres (3x3, ligne par ligne), SRATIONAL
  CalibrationIlluminant1/2 : SHORT (17 = Standard A, 21 = D65)
  ProfileHueSatMapDims = (hue, sat, val) ; ProfileHueSatMapData1/2 : FLOAT
  ProfileHueSatMapEncoding, ProfileLookTableEncoding : LONG (0 linéaire, 1 sRGB)
  ProfileLookTableDims = (hue, sat, val) ; ProfileLookTableData : FLOAT
  ProfileToneCurve : liste de points (x, y) dans [0,1] (ou liste plate x0,y0,x1,y1…)
  ProfileEmbedPolicy : LONG (0 autoriser la copie, 1 intégré seulement, 2 copie interdite, 3 aucune restriction)
  BaselineExposureOffset : SRATIONAL ; DefaultBlackRender : LONG (0 auto, 1 aucun)
Tables HSV : pour chaque valeur v, chaque teinte h, chaque saturation s (s le plus
interne) : 3 floats (décalage de teinte en degrés, facteur de saturation, facteur de
valeur). Indice = ((v*hue + h)*sat + s)*3. Neutre = (0, 1, 1).

Sources : spécification DNG 1.7.x (Adobe), chap. « Camera Profile Tags » :
ColorMatrix1/2 (50721/2), CalibrationIlluminant1/2 (50778/9), ProfileCalibrationSignature
(50932), ProfileName (50936), ProfileHueSatMapDims (50937), ProfileHueSatMapData1/2
(50938/9), ProfileToneCurve (50940), ProfileEmbedPolicy (50941), ProfileCopyright
(50942), ForwardMatrix1/2 (50964/5), ProfileLookTableDims (50981), ProfileLookTableData
(50982), ProfileHueSatMapEncoding (51107), ProfileLookTableEncoding (51108),
BaselineExposureOffset (51109), DefaultBlackRender (51110). Conteneur DCP : en-tête
« IIRC » + 0x0008 puis IFD à l'offset 8 (modèle des profils Adobe, relu ici).
"""
import struct
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

# nom -> (tag, type) ; types TIFF : 2 ASCII, 3 SHORT, 4 LONG, 10 SRATIONAL, 11 FLOAT
TAGS = {
    "UniqueCameraModel": (50708, 2), "ColorMatrix1": (50721, 10), "ColorMatrix2": (50722, 10),
    "CalibrationIlluminant1": (50778, 3), "CalibrationIlluminant2": (50779, 3),
    "ProfileCalibrationSignature": (50932, 2), "ProfileName": (50936, 2),
    "ProfileHueSatMapDims": (50937, 4), "ProfileHueSatMapData1": (50938, 11),
    "ProfileHueSatMapData2": (50939, 11), "ProfileToneCurve": (50940, 11),
    "ProfileEmbedPolicy": (50941, 4), "ProfileCopyright": (50942, 2),
    "ForwardMatrix1": (50964, 10), "ForwardMatrix2": (50965, 10),
    "ProfileLookTableDims": (50981, 4), "ProfileLookTableData": (50982, 11),
    "ProfileHueSatMapEncoding": (51107, 4), "ProfileLookTableEncoding": (51108, 4),
    "BaselineExposureOffset": (51109, 10), "DefaultBlackRender": (51110, 4),
}
PAR_NUM = {v[0]: k for k, v in TAGS.items()}
TAILLES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
FORMATS = {1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i", 11: "f", 12: "d"}


def _rationnel(x):
    """float -> (num, den) int32, dénominateur <= 10^6 (exact pour les valeurs à 4-6 décimales)."""
    n, d = round(x * 10000), 10000  # convention Adobe : dénominateur 10000 quand c'est exact
    if abs(n / d - x) > 1e-9:
        f = Fraction(x).limit_denominator(10 ** 6)
        n, d = f.numerator, f.denominator
    if abs(n) > 2 ** 31 - 1:
        raise ValueError(f"rationnel hors int32 : {x}")
    return n, d


def _encoder(typ, val):
    """-> (count, octets) pour un tag."""
    if typ == 2:
        b = val.encode("latin-1") + b"\0"
        return len(b), b
    val = list(val)
    if typ == 10:
        flat = [c for x in val for c in _rationnel(x)]
        return len(val), struct.pack(f"<{len(flat)}i", *flat)
    if typ == 5:
        flat = [c for x in val for c in (Fraction(x).limit_denominator(10 ** 6).numerator,
                                          Fraction(x).limit_denominator(10 ** 6).denominator)]
        return len(val), struct.pack(f"<{len(flat)}I", *flat)
    return len(val), struct.pack(f"<{len(val)}{FORMATS[typ]}", *val)


def _normaliser(profil):
    """dict utilisateur -> {tag: (type, valeur)} avec contrôles de cohérence."""
    out = {}
    for cle, v in profil.items():
        if isinstance(cle, int):
            out[cle] = (v[0], v[1])
            continue
        if cle not in TAGS:
            raise KeyError(f"tag inconnu : {cle}")
        tag, typ = TAGS[cle]
        if cle == "ProfileToneCurve":
            v = [c for p in v for c in (p if hasattr(p, "__len__") else [p])]
            if len(v) % 2 or len(v) < 4:
                raise ValueError("ProfileToneCurve : au moins 2 points (x, y)")
            xs = v[0::2]
            if any(b <= a for a, b in zip(xs, xs[1:])) or min(v) < 0 or max(v) > 1:
                raise ValueError("ProfileToneCurve : x strictement croissants, valeurs dans [0,1]")
        elif cle in ("ColorMatrix1", "ColorMatrix2", "ForwardMatrix1", "ForwardMatrix2"):
            v = [c for l in v for c in (l if hasattr(l, "__len__") else [l])]
            if len(v) != 9:
                raise ValueError(f"{cle} : 9 valeurs attendues")
        elif typ == 4 or typ == 3 or typ == 10 or typ == 11:
            if not isinstance(v, (list, tuple)) and not hasattr(v, "tolist"):
                v = [v]
            elif hasattr(v, "tolist"):
                v = v.tolist()
        out[tag] = (typ, v)
    # cohérence des tables
    for dims, data, nom in ((50937, (50938, 50939), "HueSatMap"), (50981, (50982,), "LookTable")):
        for t in data:
            if t in out:
                if dims not in out:
                    raise ValueError(f"{nom} : Dims manquant")
                h, s, vv = out[dims][1]
                attendu = h * s * vv * 3
                if len(out[t][1]) != attendu:
                    raise ValueError(f"{nom} : {len(out[t][1])} valeurs, {attendu} attendues")
    if 50981 in out and 50982 not in out:
        raise ValueError("LookTable : Data manquant")
    return out


def ecrire(chemin, profil):
    """Écrit un DCP. Structure : en-tête, IFD (tags triés), puis données alignées sur 2 octets (mot TIFF)."""
    tags = _normaliser(profil)
    n = len(tags)
    debut_donnees = 8 + 2 + 12 * n + 4
    entrees, blob = [], bytearray()
    for tag in sorted(tags):
        typ, val = tags[tag]
        cnt, brut = _encoder(typ, val)
        if len(brut) <= 4:
            entrees.append(struct.pack("<HHI", tag, typ, cnt) + brut.ljust(4, b"\0"))
        else:
            entrees.append(struct.pack("<HHII", tag, typ, cnt, debut_donnees + len(blob)))
            blob += brut
            blob += b"\0" * (len(blob) % 2)  # alignement sur mot (2 octets), comme Adobe
    data = b"IIRC" + struct.pack("<I", 8) + struct.pack("<H", n) + b"".join(entrees) \
        + struct.pack("<I", 0) + bytes(blob)
    Path(chemin).write_bytes(data)
    return len(data)


def lire_brut(chemin):
    """-> {tag: (type, valeurs)} ; rationnels en float, ASCII en str."""
    d = Path(chemin).read_bytes()
    if d[:4] != b"IIRC" or struct.unpack_from("<I", d, 4)[0] < 8:
        raise ValueError("pas un DCP (magie IIRC attendue)")
    off = struct.unpack_from("<I", d, 4)[0]
    n = struct.unpack_from("<H", d, off)[0]
    out = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from("<HHII", d, off + 2 + 12 * i)
        taille = TAILLES[typ] * cnt
        pos = off + 2 + 12 * i + 8 if taille <= 4 else val
        brut = d[pos:pos + taille]
        if typ == 2:
            v = brut.rstrip(b"\0").decode("latin-1")
        elif typ == 10:
            p = struct.unpack(f"<{2 * cnt}i", brut)
            v = [a / b if b else 0.0 for a, b in zip(p[0::2], p[1::2])]
        elif typ == 5:
            p = struct.unpack(f"<{2 * cnt}I", brut)
            v = [a / b if b else 0.0 for a, b in zip(p[0::2], p[1::2])]
        elif typ in FORMATS:
            v = list(struct.unpack(f"<{cnt}{FORMATS[typ]}", brut))
        else:
            v = brut.hex()
        out[tag] = (typ, v)
    return out


def lire(chemin):
    """-> dict nom -> valeur (tags inconnus : clé = numéro entier, valeur (type, valeurs))."""
    return {PAR_NUM.get(t, t): (v if t in PAR_NUM else (typ, v))
            for t, (typ, v) in lire_brut(chemin).items()}


def comparer(a, b, tol=1e-6):
    """Compare deux dicts de lire() ; -> liste de différences (vide = identiques)."""
    diffs = []
    for k in sorted(set(a) | set(b), key=str):
        if k not in a or k not in b:
            diffs.append(f"{k} : absent d'un côté")
            continue
        x, y = a[k], b[k]
        if isinstance(k, int):
            x, y = x[1], y[1]
        if isinstance(x, str) or isinstance(y, str):
            if x != y:
                diffs.append(f"{k} : {x!r} != {y!r}")
        elif len(x) != len(y):
            diffs.append(f"{k} : longueur {len(x)} != {len(y)}")
        else:
            m = max((abs(p - q) for p, q in zip(x, y)), default=0)
            if m > tol:
                diffs.append(f"{k} : écart max {m}")
    return diffs


ADOBE = Path("/Library/Application Support/Adobe/CameraRaw/CameraProfiles/Adobe Standard/"
             "Hasselblad 100-22-Coated6 Adobe Standard.dcp")
import os  # noqa: E402
TMP = Path(os.environ.get('HNCS_WORKDIR', 'workdir')).resolve() / 'tmp-dcp'


def _exiftool(chemin):
    """-> (ok, texte, bruit) ; -m : l'avertissement mineur « large array » d'exiftool (présent aussi sur
    les profils Adobe) est écarté pour que les tables soient décodées ; tout autre message échoue."""
    r = subprocess.run(["exiftool", "-m", "-a", "-G1", "-s", str(chemin)],
                       capture_output=True, text=True)
    bruit = [l for l in r.stdout.splitlines() + r.stderr.splitlines()
             if "Warning" in l or "Error" in l]
    return r.returncode == 0 and not bruit, r.stdout, bruit


def _auto_test():
    import numpy as np
    TMP.mkdir(parents=True, exist_ok=True)
    ok = True

    def verifie(nom, cond, detail=""):
        nonlocal ok
        print(("OK   " if cond else "ECHEC"), nom, detail)
        ok = ok and cond

    # 1. réécriture à l'identique du profil Adobe
    ref = lire(ADOBE)
    brut_ref = lire_brut(ADOBE)
    p = {k: v for k, v in ref.items()}
    for k, v in list(p.items()):
        if isinstance(k, int):
            p[k] = v
    cible = TMP / "adobe-reecrit.dcp"
    ecrire(cible, p)
    d = comparer(ref, lire(cible))
    verifie("Adobe réécrit : tous les tags égaux", not d, "; ".join(d))
    verifie("Adobe réécrit : mêmes numéros de tags", sorted(brut_ref) == sorted(lire_brut(cible)))
    verifie("Adobe réécrit : mêmes types",
            all(brut_ref[t][0] == lire_brut(cible)[t][0] for t in brut_ref))
    verifie("Adobe réécrit : même taille", ADOBE.stat().st_size == cible.stat().st_size,
            f"{ADOBE.stat().st_size} / {cible.stat().st_size}")
    verifie("Adobe réécrit : octets identiques", ADOBE.read_bytes() == cible.read_bytes())

    # 2. profil d'essai : LookTable 36x8x8 neutre + courbe de tons
    h, s, v = 36, 8, 8
    neutre = np.tile(np.array([0.0, 1.0, 1.0], dtype=np.float32), h * s * v)
    neutre.reshape(v, h, s, 3)[3, 5, 2] = (12.5, 1.25, 0.9)  # une case non neutre
    courbe = [(0, 0), (0.25, 0.2), (0.5, 0.55), (0.75, 0.85), (1, 1)]
    essai = {
        "UniqueCameraModel": ref["UniqueCameraModel"], "ProfileName": "Essai HNCS",
        "ColorMatrix1": ref["ColorMatrix1"], "ColorMatrix2": ref["ColorMatrix2"],
        "ForwardMatrix1": ref["ForwardMatrix1"], "ForwardMatrix2": ref["ForwardMatrix2"],
        "CalibrationIlluminant1": [17], "CalibrationIlluminant2": [21],
        "ProfileCalibrationSignature": "com.thomashammoudi",
        "ProfileLookTableDims": (h, s, v), "ProfileLookTableData": neutre,
        "ProfileLookTableEncoding": 1, "ProfileHueSatMapEncoding": 1,
        "ProfileToneCurve": courbe, "ProfileEmbedPolicy": 0,
        "ProfileCopyright": "Thomas Hammoudi", "BaselineExposureOffset": 0.35,
        "DefaultBlackRender": 1,
    }
    f2 = TMP / "essai-looktable.dcp"
    ecrire(f2, essai)
    r2 = lire(f2)
    attendu = {k: ([x for pt in v for x in pt] if k == "ProfileToneCurve" else
                   v.tolist() if hasattr(v, "tolist") else v if isinstance(v, str) else
                   list(v) if isinstance(v, (list, tuple)) else [v]) for k, v in essai.items()}
    d = comparer(attendu, r2, tol=1e-6)
    verifie("Essai : tous les tags relus égaux", not d, "; ".join(d))
    verifie("Essai : LookTable 36*8*8*3 floats", len(r2["ProfileLookTableData"]) == 6912)
    verifie("Essai : tags triés dans l'IFD", list(lire_brut(f2)) == sorted(lire_brut(f2)))
    verifie("Essai : case non neutre à sa place (ordre v,h,s)",
            r2["ProfileLookTableData"][(((3 * h + 5) * s + 2) * 3):][:3] == [12.5, 1.25, np.float32(0.9).item()])
    for mauvais, nom in (({"ProfileLookTableDims": (2, 2, 2), "ProfileLookTableData": [0.0]}, "taille"),
                         ({"ProfileToneCurve": [(0.5, 0), (0.2, 1)]}, "courbe")):
        try:
            ecrire(TMP / "invalide.dcp", mauvais)
            verifie(f"Refus profil invalide ({nom})", False)
        except ValueError:
            verifie(f"Refus profil invalide ({nom})", True)

    # 3. exiftool
    for f in (cible, f2):
        e_ok, sortie, bruit = _exiftool(f)
        verifie(f"exiftool sans avertissement : {f.name}", e_ok, "; ".join(bruit))
    sortie = _exiftool(f2)[1]
    verifie("exiftool lit ProfileName et ProfileToneCurve",
            "Essai HNCS" in sortie and "ProfileToneCurve" in sortie)
    return ok


def main():
    if "--self-test" in sys.argv:
        sys.exit(0 if _auto_test() else 1)
    if len(sys.argv) > 1:
        for k, v in lire(sys.argv[1]).items():
            print(k, f"{len(v)} valeurs" if isinstance(v, list) and len(v) > 12 else v)
        return
    print(__doc__)


if __name__ == "__main__":
    main()
