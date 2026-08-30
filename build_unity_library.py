#!/usr/bin/env python3
"""
build_unity_library.py - extract a clean, Unity-ready library from the bundle zips.

Reads the source .zip files and writes out only what a Unity project actually
uses, preserving each pack's internal folder layout so that any relative texture
reference inside an FBX still resolves.

KEPT
    .fbx            Unity's native mesh format
    .glb            kept alongside for web/glTF pipelines
    .png .jpg       model textures + the standalone PSX texture libraries
    .ogg .wav       audio
    .pdf .txt       licences and readmes

DROPPED
    .obj .mtl .dae  redundant with FBX
    .blend .blend1  Blender working files (.blend1 is just an autosave backup)
    previews        marketing renders and thumbnails, never shipped
    "PSX Nature (Tree branches separated)"   a second copy of the same 49 models
    PolyRazor       a Windows .exe tool - does not belong inside a Unity project

The source zips are only ever read. Nothing is deleted or modified.

USAGE
    python build_unity_library.py "<bundle dir>" -o "<output dir>" [--dry-run]
"""
import argparse, csv, os, posixpath, sys, zipfile

KEEP_EXT = {".fbx", ".glb", ".png", ".jpg", ".jpeg", ".tga", ".ogg", ".wav", ".pdf", ".txt"}
DROP_EXT = {".obj", ".mtl", ".dae", ".blend", ".blend1", ".exe", ".efa"}
DROP_ARCHIVE_SUBSTR = ("polyrazor",)
DROP_PATH_SUBSTR = ("tree branches separated",)


def is_preview(path):
    """Marketing renders: 'Preview_1.jpg', 'thumbnail.png', 'p_0.png'."""
    leaf = posixpath.basename(path).lower()
    if leaf.startswith(("preview", "thumbnail")):
        return True
    if leaf in {"p_0.png", "p_1.png", "p_2.png", "p_3.png"}:
        return True
    return "preview" in path.lower() and leaf.endswith((".jpg", ".png"))


def wanted(archive, path):
    a, p = archive.lower(), path.lower()
    if any(s in a for s in DROP_ARCHIVE_SUBSTR):
        return False, "tool, not assets"
    if any(s in p for s in DROP_PATH_SUBSTR):
        return False, "duplicate model variant"
    ext = os.path.splitext(p)[1]
    if ext in DROP_EXT:
        return False, f"redundant/source ({ext})"
    if ext not in KEEP_EXT:
        return False, f"unused type ({ext or 'no ext'})"
    if is_preview(path):
        return False, "marketing preview"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    zips = sorted(os.path.join(a.root, f) for f in os.listdir(a.root)
                  if f.lower().endswith(".zip"))
    if not zips:
        sys.exit(f"no .zip files in {a.root}")

    kept_rows = [("pack", "path", "ext", "bytes")]
    kept_n = kept_b = drop_n = drop_b = 0
    reasons = {}

    for zp in zips:
        arc = os.path.basename(zp)
        k = b = 0
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                ok, why = wanted(arc, info.filename)
                if not ok:
                    drop_n += 1
                    drop_b += info.file_size
                    r = reasons.setdefault(why, [0, 0])
                    r[0] += 1
                    r[1] += info.file_size
                    continue
                k += 1
                b += info.file_size
                kept_rows.append((arc, info.filename,
                                  os.path.splitext(info.filename)[1].lower(),
                                  info.file_size))
                if not a.dry_run:
                    # normalise separators; zip paths are always posix
                    dest = os.path.join(a.out, *info.filename.split("/"))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(info) as src, open(dest, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
        kept_n += k
        kept_b += b
        print(f"  {k:>5,} files {b/1024**2:>8,.1f} MB   {arc}")

    print(f"\nKEPT    {kept_n:>6,} files  {kept_b/1024**3:>6.2f} GB")
    print(f"DROPPED {drop_n:>6,} files  {drop_b/1024**3:>6.2f} GB")
    for why, (c, bb) in sorted(reasons.items(), key=lambda x: -x[1][1]):
        print(f"          {c:>6,}  {bb/1024**2:>8,.0f} MB  {why}")

    if not a.dry_run:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "_manifest.csv"), "w", newline="",
                  encoding="utf-8") as fh:
            csv.writer(fh).writerows(kept_rows)
        print(f"\nWrote {a.out}")


if __name__ == "__main__":
    main()
