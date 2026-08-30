#!/usr/bin/env python3
"""
dedupe_textures.py - remove redundant texture copies left behind by build_unity_library.py.

Each pack exports its models several times (GLB, FBX, DAE, OBJ) and drops a copy
of every texture beside each export. build_unity_library.py drops the redundant
*meshes*, but their sibling texture folders survive as orphans.

Those copies cannot be matched by file hash: re-exporting a PNG changes the
encoded bytes while leaving every pixel identical. So this compares decoded pixel
data instead, and only deletes a copy when a same-named, pixel-equal image exists
elsewhere in the library. Anything genuinely unique is moved into its pack's
Textures/ folder rather than deleted - FBX files reference textures by bare
filename, so Unity resolves them wherever they sit in the project.

    python dedupe_textures.py "<library dir>" [--apply]

Runs as a dry run unless --apply is given.
"""
import argparse, os, shutil
from collections import defaultdict
import numpy as np
from PIL import Image

ORPHAN_DIRS = {"DAE", "OBJ"}
TOL = 6.0          # mean per-channel difference below this counts as "same image"


def in_orphan(dirpath):
    parts = os.path.normpath(dirpath).split(os.sep)
    return any(p in ORPHAN_DIRS for p in parts)


def pixels(path, cache):
    if path not in cache:
        try:
            cache[path] = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
        except Exception:
            cache[path] = None
    return cache[path]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lib")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    orphan, keeper = [], defaultdict(list)
    for dp, _dn, fn in os.walk(a.lib):
        for f in fn:
            if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            p = os.path.join(dp, f)
            (orphan.append(p) if in_orphan(dp) else keeper[f.lower()].append(p))

    cache = {}
    dup, uniq = [], []
    for p in orphan:
        me = pixels(p, cache)
        best = None
        for q in keeper.get(os.path.basename(p).lower(), []):
            other = pixels(q, cache)
            if me is None or other is None or me.shape != other.shape:
                continue
            d = np.abs(me.astype(np.int16) - other.astype(np.int16)).mean()
            best = d if best is None else min(best, d)
        (dup if best is not None and best < TOL else uniq).append(p)

    freed = sum(os.path.getsize(p) for p in dup)
    print(f"orphaned copies : {len(orphan):,}")
    print(f"  duplicates    : {len(dup):,}  ({freed/1024**2:,.1f} MB)")
    print(f"  unique        : {len(uniq):,}  -> moved to <Pack>/Textures/")
    if not a.apply:
        print("\ndry run - pass --apply to make the changes")
        return

    for p in uniq:
        pack = os.path.relpath(p, a.lib).split(os.sep)[0]
        dest = os.path.join(a.lib, pack, "Textures", os.path.basename(p))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(p, dest) if not os.path.exists(dest) else os.remove(p)
    for p in dup:
        if os.path.exists(p):
            os.remove(p)
    gone = 0
    for dp, _dn, _fn in os.walk(a.lib, topdown=False):
        if in_orphan(dp) and not os.listdir(dp):
            os.rmdir(dp)
            gone += 1
    print(f"\nremoved {gone} empty folders; freed {freed/1024**2:,.1f} MB")


if __name__ == "__main__":
    main()
