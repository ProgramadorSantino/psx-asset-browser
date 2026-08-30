#!/usr/bin/env python3
"""
peek_archives.py - list what is INSIDE .zip / .unitypackage files without extracting them.

Companion to index_assets.ps1 (loose files) and peek_unitypackages.py (Unity blobs).
This one covers the third case: a library shipped as plain .zip archives.

A zip stores a "central directory" at the end of the file: every entry's path,
uncompressed size and date, in one contiguous block. Reading it costs one seek -
no decompression, no extraction, no temp files. A 650 MB pack lists in
milliseconds instead of the minutes a unitypackage needs.

.unitypackage files (gzipped tar) are also handled, including ones nested inside
a zip, since those must be read sequentially.

USAGE
    python peek_archives.py "C:/Users/you/Downloads" [-o OUTDIR]

OUTPUT
    archive_contents.csv.gz   one row per asset inside every archive
    archive_summary.txt       readable overview, also printed

Nothing is written into the library and no asset files are extracted.
"""
import argparse, csv, gzip, os, sys, tarfile, time, zipfile
from collections import defaultdict

ZIP_EXT = {".zip"}
UPKG_EXT = {".unitypackage"}
# archives we cannot read without external tooling (7z / unrar not installed)
OPAQUE_EXT = {".rar", ".7z", ".gz", ".bz2", ".xz", ".iso", ".cab"}


def peek_unitypackage_stream(fileobj):
    """Yield (asset_path, bytes) from a .unitypackage given a readable stream.

    Streaming mode ("r|gz") so this works on a non-seekable member of a zip.
    Each asset lives in a GUID folder next to a tiny `pathname` entry.
    """
    names, sizes = {}, {}
    with tarfile.open(fileobj=fileobj, mode="r|gz") as t:
        for m in t:
            if not m.isfile():
                continue
            parts = m.name.strip("./").split("/")
            if len(parts) < 2:
                continue
            guid, leaf = parts[0], parts[-1]
            if leaf == "pathname":
                f = t.extractfile(m)
                if f:
                    names[guid] = f.read().decode("utf-8", "replace").strip().split("\n")[0]
            elif leaf == "asset":
                sizes[guid] = m.size
    for guid, p in names.items():
        yield p, sizes.get(guid, 0)


def peek_zip(path, rows, rel):
    """Read one zip's central directory. Recurses into nested .unitypackage."""
    n = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            ext = os.path.splitext(name)[1].lower()
            rows.append((rel, name, ext, info.file_size))
            n += 1
            if ext in UPKG_EXT:
                # a Unity blob inside the zip - stream it open too
                try:
                    with z.open(info) as inner:
                        for ap, sz in peek_unitypackage_stream(inner):
                            rows.append((f"{rel}!{name}", ap,
                                         os.path.splitext(ap)[1].lower(), sz))
                            n += 1
                except Exception as e:
                    rows.append((f"{rel}!{name}",
                                 f"<<UNREADABLE: {type(e).__name__}>>", "", 0))
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("-o", "--out", default=".")
    a = ap.parse_args()
    root, out = a.root, a.out
    os.makedirs(out, exist_ok=True)

    targets, opaque = [], []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            e = os.path.splitext(f)[1].lower()
            p = os.path.join(dp, f)
            if e in ZIP_EXT or e in UPKG_EXT:
                targets.append(p)
            elif e in OPAQUE_EXT:
                opaque.append(p)
    targets.sort()
    if not targets:
        print("No .zip or .unitypackage files found.")
        return

    total = sum(os.path.getsize(p) for p in targets)
    print(f"{len(targets)} archives, {total/1024**3:.2f} GB. Reading directories...\n")

    rows = [("archive", "asset_path", "ext", "bytes")]
    per_arc, failed = {}, []
    t0 = time.time()
    for i, p in enumerate(targets, 1):
        rel = os.path.relpath(p, root).replace("\\", "/")
        e = os.path.splitext(p)[1].lower()
        n = 0
        try:
            if e in ZIP_EXT:
                n = peek_zip(p, rows, rel)
            else:
                with open(p, "rb") as fh:
                    for apath, sz in peek_unitypackage_stream(fh):
                        rows.append((rel, apath, os.path.splitext(apath)[1].lower(), sz))
                        n += 1
        except Exception as ex:
            rows.append((rel, f"<<UNREADABLE: {type(ex).__name__}>>", "", 0))
            failed.append((rel, f"{type(ex).__name__}: {ex}"))
        per_arc[rel] = n
        print(f"  [{i}/{len(targets)}] {n:>7,} entries  {rel[:66]}")

    with gzip.open(os.path.join(out, "archive_contents.csv.gz"), "wt",
                   newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)

    agg = defaultdict(lambda: [0, 0])
    for _a, _p, ext, sz in rows[1:]:
        g = agg[ext or "(none)"]
        g[0] += 1
        g[1] += sz

    L = ["ARCHIVE CONTENTS",
         f"root      : {root}",
         f"archives  : {len(targets)}",
         f"entries   : {len(rows)-1:,}",
         f"elapsed   : {time.time()-t0:.0f}s", "",
         f"{'EXT':<16}{'FILES':>10}{'SIZE(MB)':>14}"]
    for e, (c, b) in sorted(agg.items(), key=lambda x: -x[1][1])[:40]:
        L.append(f"{e:<16}{c:>10,}{b/1024**2:>14,.1f}")
    L += ["", f"{'ARCHIVE':<70}{'ENTRIES':>9}"]
    for k, v in sorted(per_arc.items(), key=lambda x: -x[1]):
        L.append(f"{k[:69]:<70}{v:>9,}")
    if failed:
        L += ["", "UNREADABLE ARCHIVES"] + [f"  {k}  {v}" for k, v in failed]
    if opaque:
        L += ["", f"NOT READ - needs 7z/unrar ({len(opaque)} files)"]
        L += [f"  {os.path.relpath(p, root)}" for p in opaque[:40]]

    with open(os.path.join(out, "archive_summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n" + "\n".join(L[:14]))
    print(f"\nDone -> {os.path.join(out, 'archive_contents.csv.gz')}")


if __name__ == "__main__":
    main()
