#!/usr/bin/env python3
"""
build_relations.py - work out how the models relate to each other.

Answers three questions the browser could not before:

  variants   Which models are the same thing in another flavour?
             Derived from the naming scheme: pipe_cx_1, pipe_cx_2, pipe_cx_3 are
             one family. Suffix codes (_hr, _mp, _mx, _rtx...) mark the pack the
             art came from, so they are stripped when grouping.

  goes_with  Which models were built to sit in the same scene?
             Two models sharing a texture were painted from the same sheet by the
             same artist, so they read as belonging together. Scored by how much
             of their texture sets overlap, and biased against textures used by
             half the pack (concrete is not a meaningful connection).

  similar    Which models simply look alike?
             A 16x16 difference hash of each rendered thumbnail, compared by
             Hamming distance. Catches silhouette and value similarity across
             packs and categories, which the other two measures miss.

    python build_relations.py <thumbs dir> -o relations.json
"""
import argparse, json, math, os, re
from collections import defaultdict, Counter
import numpy as np
from PIL import Image

# trailing variant/pack codes: barrel_hr_4_1 -> barrel, doorway_rg_1_wide -> doorway_wide
PACK_CODE = re.compile(r"_(?:hr|mp|mx|mh|hm|cx|dx|rg|rtx|emx|emh|bnk|ufx|sfx)\b", re.I)
TRAIL_NUM = re.compile(r"(?:_\d+)+$")


def family(name):
    s = name.lower()
    s = PACK_CODE.sub("", s)
    s = TRAIL_NUM.sub("", s)
    s = re.sub(r"_(\d+)_", "_", s)
    s = re.sub(r"__+", "_", s).strip("_")
    return s or name.lower()


def dhash(path, size=16):
    """Difference hash: compare each pixel to its right neighbour. Robust to the
    slight exposure differences between renders, unlike a raw pixel compare."""
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (24, 27, 28, 255))     # flatten transparency
    im = Image.alpha_composite(bg, im).convert("L").resize((size + 1, size), Image.LANCZOS)
    a = np.asarray(im, dtype=np.int16)
    return np.packbits((a[:, 1:] > a[:, :-1]).flatten())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("thumbs")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()

    models = json.load(open(os.path.join(a.thumbs, "models.json"), encoding="utf-8"))
    print(f"{len(models):,} models")

    for m in models:
        m["name"] = os.path.basename(m["rel"])[:-4]
        m["fam"] = family(m["name"])
        m["tex"] = {re.sub(r"\.\d{3}$", "", t).lower() for t in m.get("textures", [])}

    # ---- variants ----------------------------------------------------------
    fams = defaultdict(list)
    for m in models:
        fams[m["fam"]].append(m["key"])
    multi = {k: v for k, v in fams.items() if len(v) > 1}
    print(f"  families      : {len(fams):,} ({len(multi):,} with more than one member)")

    # ---- goes_with: shared textures, rare textures weighted higher ----------
    tex_users = defaultdict(list)
    for m in models:
        for t in m["tex"]:
            tex_users[t].append(m["key"])
    # inverse-frequency weight; a texture on 300 models says almost nothing
    N = len(models)
    weight = {t: math.log(N / len(u)) for t, u in tex_users.items() if u}
    by_key = {m["key"]: m for m in models}

    goes = {}
    for m in models:
        if not m["tex"]:
            continue
        score = defaultdict(float)
        for t in m["tex"]:
            if len(tex_users[t]) > N * 0.25:       # ubiquitous, skip
                continue
            for k in tex_users[t]:
                if k != m["key"]:
                    score[k] += weight[t]
        if not score:
            continue
        ranked = sorted(score.items(), key=lambda x: -x[1])
        # prefer partners outside the model's own family - a variant is not news
        out = [k for k, _ in ranked if by_key[k]["fam"] != m["fam"]][:a.top]
        if out:
            goes[m["key"]] = out
    print(f"  goes_with     : {len(goes):,} models have a texture-based partner")

    # ---- similar: perceptual hash over the renders --------------------------
    keys, hashes = [], []
    for m in models:
        p = os.path.join(a.thumbs, m["key"] + ".png")
        if os.path.exists(p):
            keys.append(m["key"])
            hashes.append(dhash(p))
    H = np.unpackbits(np.array(hashes, dtype=np.uint8), axis=1).astype(np.int8)
    print(f"  hashed        : {len(keys):,} thumbnails ({H.shape[1]} bits)")

    sim = {}
    B = 256
    for i0 in range(0, len(keys), B):
        blk = H[i0:i0 + B]
        # Hamming distance = number of differing bits
        d = (blk[:, None, :] != H[None, :, :]).sum(axis=2)
        for r, gi in enumerate(range(i0, min(i0 + B, len(keys)))):
            d[r, gi] = 9999
            order = np.argsort(d[r])[:a.top * 3]
            me = by_key[keys[gi]]
            picks = []
            for j in order:
                if d[r, j] > 70:                    # too different to be useful
                    break
                cand = by_key[keys[j]]
                if cand["fam"] == me["fam"]:        # variants already listed
                    continue
                picks.append(keys[j])
                if len(picks) >= a.top:
                    break
            if picks:
                sim[keys[gi]] = picks
        print(f"    {min(i0+B, len(keys)):>5}/{len(keys)}", end="\r", flush=True)
    print(f"\n  similar       : {len(sim):,} models have a visual neighbour")

    out = {
        "families": {k: v for k, v in multi.items()},
        "fam_of": {m["key"]: m["fam"] for m in models},
        "goes_with": goes,
        "similar": sim,
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"\nwrote {a.out} ({os.path.getsize(a.out)/1024:,.0f} KB)")


if __name__ == "__main__":
    main()
