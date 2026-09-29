#!/usr/bin/env python3
"""
build_relations.py - work out how the models relate to each other.

Answers three questions the browser could not before:

  variants   Which models are the same thing in another flavour?
             Every model has a family key, stored in families.json. A model not
             in that file yet is proposed one from its name (metal_barrel_hr_1 ..
             metal_barrel_hr_4_1 are one family) and the file is written back, so
             an assignment never changes under you. To merge two families - the
             oil drums from two packs, say - give them the same key there; to split
             one, give some of its models a new key.

  goes_with  Which models were built to sit in the same scene?
             Two models sharing a texture were painted from the same sheet by the
             same artist, so they read as belonging together. Scored by how much
             of their texture sets overlap, and biased against textures used by
             half the pack (concrete is not a meaningful connection).

  similar    Which models simply look alike?
             A 16x16 difference hash of each rendered thumbnail, compared by
             Hamming distance. Catches silhouette and value similarity across
             packs and categories, which the other two measures miss.

    python build_relations.py <thumbs dir> -o relations.json \
        [--families families.json] [--descriptions descriptions.json]
"""
import argparse, json, math, os, re
from collections import Counter, defaultdict
import numpy as np
from PIL import Image
from packs import family_from_name, model_name, propose_family


def assign_families(models, path, described):
    """Read the stored family of every model, proposing one for any model that has
    none, and write the file back. Returns {model key: family key}."""
    store = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            store = json.load(fh)
    known = set(described) | set(store.values())
    # A new model follows its siblings - models whose names say the same family -
    # to whatever family they were given, so a merge made by hand holds when a
    # pack update adds another drum.
    given = defaultdict(Counter)
    for k, fam in store.items():
        given[family_from_name(k.split("__")[-1])][fam] += 1
    new = {}
    for m in models:
        if m["key"] not in store:
            name = model_name(m["rel"])
            sib = given.get(family_from_name(name))
            new[m["key"]] = sib.most_common(1)[0][0] if sib else propose_family(name, known)
    store.update(new)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=0, sort_keys=True, ensure_ascii=False)
        fh.write("\n")

    here = {m["key"] for m in models}
    print(f"  families.json : {len(here) - len(new):,} already assigned, {len(new):,} new"
          + (f", {len(set(store) - here):,} not in this library (kept)" if set(store) - here else ""))
    # a proposed family that spans packs is usually two different objects that
    # happen to share a name - worth a look before descriptions get written
    packs = defaultdict(set)
    for m in models:
        if m["key"] in new:
            packs[new[m["key"]]].add(m["rel"].split("/")[0])
    mixed = sorted(f for f, ps in packs.items() if len(ps) > 1)
    if mixed:
        print(f"  check         : {len(mixed)} new families span more than one pack: "
              + ", ".join(mixed[:8]) + (" ..." if len(mixed) > 8 else ""))
    return {m["key"]: store[m["key"]] for m in models}


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
    ap.add_argument("--families", default="families.json",
                    help="stored family key per model; created if missing, then kept")
    ap.add_argument("--descriptions", default="descriptions.json",
                    help="described families, preferred when proposing a new one")
    a = ap.parse_args()

    models = json.load(open(os.path.join(a.thumbs, "models.json"), encoding="utf-8"))
    print(f"{len(models):,} models")

    described = {}
    if a.descriptions and os.path.exists(a.descriptions):
        described = json.load(open(a.descriptions, encoding="utf-8"))
    fam_of = assign_families(models, a.families, described)
    for m in models:
        m["fam"] = fam_of[m["key"]]
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
