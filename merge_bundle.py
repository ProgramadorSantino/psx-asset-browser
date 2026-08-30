#!/usr/bin/env python3
r"""
merge_bundle.py - add a second bundle's zips into an existing library, skipping
anything already present.

Applies the same keep/drop rules as build_unity_library.py, then compares every
surviving candidate against the library it is merging into:

  * images   - compared by decoded pixels, because re-exporting a PNG changes the
               bytes while leaving the picture identical (this is what made a
               plain hash check useless on the first bundle)
  * everything else - compared by SHA-1 of the file contents

With --strip the per-volume wrapper folder is dropped, and with --group every
sub-pack is filed under one folder, so the browser lists the bundle as a single
pack whose categories are the sub-packs - 17 folders of five assets each would
otherwise swamp the pack filter.

    python merge_bundle.py "<bundle dir>" "<library dir>" [--apply]
        [--group "Mystery Bundle"] [--strip ".* vol\. \d+$"]

Dry run unless --apply is given. The source zips are only ever read.
"""
import argparse, hashlib, io, os, posixpath, re, sys, zipfile
from collections import defaultdict
import numpy as np
from PIL import Image

KEEP_EXT = {".fbx", ".glb", ".png", ".jpg", ".jpeg", ".tga", ".ogg", ".wav", ".pdf", ".txt"}
DROP_EXT = {".obj", ".mtl", ".dae", ".blend", ".blend1", ".exe", ".efa"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tga"}


def is_preview(path):
    leaf = posixpath.basename(path).lower()
    return (leaf.startswith(("preview", "thumbnail"))
            or leaf in {"p_0.png", "p_1.png", "p_2.png", "p_3.png"})


def wanted(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in DROP_EXT:
        return False, f"redundant/source ({ext})"
    if ext not in KEEP_EXT:
        return False, f"unused type ({ext or 'no ext'})"
    if is_preview(path):
        return False, "marketing preview"
    return True, ""


def dest_for(path, strip=None, group=None, orphans="Misc"):
    """Map a path inside a zip to its place in the library.

    `strip` drops a per-volume wrapper folder ("... vol. 7/"), so the sub-pack
    inside becomes the meaningful name. `group` files every sub-pack under one
    folder, which keeps a bundle of many tiny packs from swamping the browser's
    pack filter with 17 entries of five assets each.
    """
    parts = [p for p in path.split("/") if p]
    if strip and parts and re.match(strip, parts[0]):
        parts = parts[1:]
    if not parts:
        return None
    if len(parts) == 1:                      # a stray file at the volume root
        parts = [orphans] + parts
    return "/".join(([group] if group else []) + parts)


def pixels(data):
    try:
        return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"), dtype=np.uint8)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("lib")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--group", default=None, metavar="NAME",
                    help="file every sub-pack under this one folder, so the browser "
                         "lists the bundle as a single pack")
    ap.add_argument("--strip", default=None, metavar="REGEX",
                    help=r"drop a per-volume wrapper folder, e.g. \".* vol\. \d+$\"")
    ap.add_argument("--orphans", default="Misc", metavar="NAME",
                    help="folder for files sitting loose at a volume root")
    a = ap.parse_args()

    # ---- fingerprint the existing library -----------------------------------
    print("fingerprinting library...", flush=True)
    lib_sha, lib_img = set(), defaultdict(list)
    for dp, _dn, fn in os.walk(a.lib):
        for f in fn:
            p = os.path.join(dp, f)
            ext = os.path.splitext(f)[1].lower()
            try:
                blob = open(p, "rb").read()
            except OSError:
                continue
            lib_sha.add(hashlib.sha1(blob).hexdigest())
            if ext in IMG_EXT:
                px = pixels(blob)
                if px is not None:
                    lib_img[f.lower()].append(px)
    print(f"  {len(lib_sha):,} files, {sum(len(v) for v in lib_img.values()):,} images\n")

    zips = sorted(os.path.join(a.bundle, f) for f in os.listdir(a.bundle)
                  if f.lower().endswith(".zip"))
    new, dup, dropped = [], [], defaultdict(lambda: [0, 0])
    seen_in_bundle = set()

    for zp in zips:
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                ok, why = wanted(info.filename)
                if not ok:
                    dropped[why][0] += 1
                    dropped[why][1] += info.file_size
                    continue
                dest = dest_for(info.filename, a.strip, a.group, a.orphans)
                if dest is None:
                    continue
                blob = z.read(info)
                sha = hashlib.sha1(blob).hexdigest()
                ext = os.path.splitext(dest)[1].lower()
                reason = None
                if sha in lib_sha:
                    reason = "identical file"
                elif sha in seen_in_bundle:
                    reason = "duplicate within bundle"
                elif ext in IMG_EXT:
                    px = pixels(blob)
                    for other in lib_img.get(os.path.basename(dest).lower(), []):
                        if px is not None and px.shape == other.shape and \
                           np.abs(px.astype(np.int16) - other.astype(np.int16)).mean() < 6:
                            reason = "same image, re-encoded"
                            break
                if reason:
                    dup.append((dest, info.file_size, reason))
                    continue
                seen_in_bundle.add(sha)
                new.append((dest, info.file_size, blob if a.apply else None))

    nb = sum(x[1] for x in new)
    db = sum(x[1] for x in dup)
    print(f"NEW        {len(new):>5} files  {nb/1024**2:>8,.1f} MB")
    print(f"DUPLICATE  {len(dup):>5} files  {db/1024**2:>8,.1f} MB")
    for r, (c, b) in sorted(dropped.items(), key=lambda x: -x[1][1]):
        print(f"DROPPED    {c:>5} files  {b/1024**2:>8,.1f} MB  {r}")

    packs = defaultdict(lambda: [0, 0])
    for d, b, _ in new:
        seg = d.split("/")
        # with --group the first segment is identical for everything, so
        # report the sub-pack - otherwise every row collapses into one
        k = seg[1] if (a.group and len(seg) > 2) else seg[0]
        packs[k][0] += 1
        packs[k][1] += b
    label = "NEW CONTENT BY SUB-PACK" if a.group else "NEW CONTENT BY PACK"
    print(f"\n{label:<48}{'FILES':>7}{'MB':>9}")
    for k, (c, b) in sorted(packs.items(), key=lambda x: -x[1][1]):
        print(f"  {k[:45]:<46}{c:>7}{b/1024**2:>9,.1f}")
    if dup:
        print(f"\nduplicates ({len(dup)}):")
        for d, b, r in dup[:15]:
            print(f"  {r:<24} {d[:64]}")
        if len(dup) > 15:
            print(f"  ... +{len(dup)-15} more")

    if not a.apply:
        print("\ndry run - pass --apply to merge")
        return
    for d, _b, blob in new:
        p = os.path.join(a.lib, *d.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(blob)
    print(f"\nmerged {len(new)} files into {a.lib}")


if __name__ == "__main__":
    main()
