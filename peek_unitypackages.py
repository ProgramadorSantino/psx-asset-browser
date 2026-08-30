#!/usr/bin/env python3
"""
peek_unitypackages.py — list what is INSIDE .unitypackage files without importing them.

A .unitypackage is a gzipped tar. Every asset sits in a folder named after its
GUID, alongside a tiny `pathname` file holding its real "Assets/..." path. So the
contents are fully listable without Unity and without extracting anything.

USAGE
    python3 peek_unitypackages.py "D:/Assets/Bundle"

OUTPUT (next to this script)
    unitypackage_contents.csv.gz   one row per asset inside every package
    unitypackage_summary.txt       readable overview, also printed

Nothing is written into the bundle and no asset files are extracted - only the
few-byte `pathname` entries are read out of the stream.

NOTE ON SPEED
    gzip is sequential, so each package is decompressed in a single pass to reach
    its last entry. Expect roughly 1-3 minutes per GB. Run it once, keep the CSV.
"""
import csv, gzip, io, os, sys, tarfile, time
from collections import defaultdict


def peek(path):
    """Yield (asset_path, approx_bytes) for each asset inside one .unitypackage."""
    out, sizes = {}, {}
    with tarfile.open(path, "r:gz") as t:
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
                    out[guid] = f.read().decode("utf-8", "replace").strip().split("\n")[0]
            elif leaf == "asset":
                sizes[guid] = m.size
    for guid, p in out.items():
        yield p, sizes.get(guid, 0)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    pkgs = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if f.lower().endswith(".unitypackage"):
                pkgs.append(os.path.join(dp, f))
    pkgs.sort()
    if not pkgs:
        print("No .unitypackage files found - your bundle is loose files, so the "
              "plain index already covers it.")
        return

    total = sum(os.path.getsize(p) for p in pkgs)
    print(f"{len(pkgs)} packages, {total/1024**3:.2f} GB. Reading...\n")

    rows = [("package", "asset_path", "ext", "bytes")]
    per_pkg = {}
    t0 = time.time()
    for i, p in enumerate(pkgs, 1):
        rel = os.path.relpath(p, root)
        n = 0
        try:
            for ap, sz in peek(p):
                ext = os.path.splitext(ap)[1].lower()
                rows.append((rel, ap, ext, sz))
                n += 1
        except Exception as e:                       # a corrupt or odd package
            rows.append((rel, f"<<UNREADABLE: {type(e).__name__}>>", "", 0))
        per_pkg[rel] = n
        print(f"  [{i}/{len(pkgs)}] {n:>6} assets  {rel[:70]}")

    with gzip.open("unitypackage_contents.csv.gz", "wt", newline="") as fh:
        csv.writer(fh).writerows(rows)

    agg = defaultdict(lambda: [0, 0])
    for _pkg, _ap, ext, sz in rows[1:]:
        a = agg[ext or "(none)"]; a[0] += 1; a[1] += sz

    lines = ["UNITYPACKAGE CONTENTS",
             f"packages : {len(pkgs)}",
             f"assets   : {len(rows)-1:,}",
             f"elapsed  : {time.time()-t0:.0f}s", "",
             f"{'EXT':<14}{'FILES':>10}{'SIZE(MB)':>12}"]
    for e, (c, b) in sorted(agg.items(), key=lambda x: -x[1][1])[:40]:
        lines.append(f"{e:<14}{c:>10,}{b/1024**2:>12,.1f}")
    lines += ["", f"{'PACKAGE':<64}{'ASSETS':>8}"]
    for k, v in sorted(per_pkg.items(), key=lambda x: -x[1]):
        lines.append(f"{k[:63]:<64}{v:>8,}")

    open("unitypackage_summary.txt", "w").write("\n".join(lines))
    print("\n" + "\n".join(lines[:12]))
    print("\nDone. Send: unitypackage_contents.csv.gz")


if __name__ == "__main__":
    main()
