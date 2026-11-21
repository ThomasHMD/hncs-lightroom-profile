#!/usr/bin/env python3
"""Fabrique la variante X2D (1re generation) du profil HNCS.

Le profil X2D II est cle sur le nom d'appareil d'Adobe `Hasselblad 100-22-Coated6`.
Le X2D 100C (2022) porte `Hasselblad 100-20-Coated6`. Meme capteur, memes matrices :
la variante ne change que ce nom (meme longueur, donc un seul octet differe).
Idee et test : u/ubiquitousuk (Reddit, r/hasselblad).

    python3 tools/variante_x2d.py            # ecrit release/HNCS-Hasselblad-X2D-100C.dcp
    python3 tools/variante_x2d.py --self-test
"""
import sys, pathlib

RACINE = pathlib.Path(__file__).resolve().parent.parent
SOURCE = RACINE / "release" / "HNCS-Hasselblad-X2D-II.dcp"
SORTIE = RACINE / "release" / "HNCS-Hasselblad-X2D-100C.dcp"
ANCIEN, NOUVEAU = b"Hasselblad 100-22-Coated6", b"Hasselblad 100-20-Coated6"


def fabriquer(donnees: bytes) -> bytes:
    assert len(ANCIEN) == len(NOUVEAU)
    if donnees.count(ANCIEN) != 1:
        raise SystemExit(f"attendu : une seule occurrence de {ANCIEN!r}, trouve {donnees.count(ANCIEN)}")
    return donnees.replace(ANCIEN, NOUVEAU)


def main():
    if "--self-test" in sys.argv:
        src = SOURCE.read_bytes()
        out = fabriquer(src)
        diff = [i for i, (a, b) in enumerate(zip(src, out)) if a != b]
        assert len(src) == len(out) and len(diff) == 1, diff
        assert NOUVEAU in out and ANCIEN not in out
        print("ok : 1 octet change, meme taille")
        return
    SORTIE.write_bytes(fabriquer(SOURCE.read_bytes()))
    print("ecrit :", SORTIE)


if __name__ == "__main__":
    main()
