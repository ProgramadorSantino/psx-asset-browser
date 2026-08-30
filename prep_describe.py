#!/usr/bin/env python3
"""
prep_describe.py - split the model families into shards for description passes.

Descriptions are written per family, not per model: "metal_barrel_hr" covers all
five barrels, so 1,361 models collapse to 588 units of work.

    python prep_describe.py <thumbs dir> <relations.json> -o <shard dir> [-n 5]
"""
import argparse, json, os
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("thumbs")
    ap.add_argument("relations")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("-n", "--shards", type=int, default=5)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    models = json.load(open(os.path.join(a.thumbs, "models.json"), encoding="utf-8"))
    rel = json.load(open(a.relations, encoding="utf-8"))
    fam_of = rel["fam_of"]

    by_fam = defaultdict(list)
    for m in models:
        by_fam[fam_of[m["key"]]].append(m)

    fams = []
    for fam, ms in sorted(by_fam.items()):
        ms.sort(key=lambda m: m["key"])
        rep = ms[len(ms) // 2]                      # middle member as the exemplar
        names = [os.path.basename(m["rel"])[:-4] for m in ms]
        packs = sorted({m["rel"].split("/")[0] for m in ms})
        dims = rep.get("dim", [0, 0, 0])
        tex = sorted({t for m in ms for t in m.get("textures", [])})[:5]
        fams.append({
            "family": fam,
            "count": len(ms),
            "names": names[:10],
            "pack": packs[0] if len(packs) == 1 else packs,
            "size_m": dims,
            "tris": rep.get("tris", 0),
            "textures": tex,
            "thumb": os.path.abspath(os.path.join(a.thumbs, rep["key"] + ".png")),
        })

    # round-robin so every shard gets a mix of packs and sizes, not one alphabetical block
    shards = [[] for _ in range(a.shards)]
    for i, f in enumerate(fams):
        shards[i % a.shards].append(f)
    for i, sh in enumerate(shards, 1):
        p = os.path.join(a.out, f"shard_{i}.json")
        json.dump(sh, open(p, "w", encoding="utf-8"), indent=1)
        print(f"  shard_{i}.json  {len(sh):>4} families")
    print(f"\n{len(fams)} families total -> {a.out}")


if __name__ == "__main__":
    main()
