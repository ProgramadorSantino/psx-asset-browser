#!/usr/bin/env python3
"""
merge_descriptions.py - combine the per-shard description files into one map.

Validates as it goes: every family in the shards must be described exactly once,
and the length limits must hold, so a bad shard is caught here rather than
showing up as a broken card in the browser.

    python merge_descriptions.py <shard dir> -o descriptions.json
"""
import argparse, glob, json, os, re

WHAT_MAX, USE_MAX = 90, 120
# marketing tics the descriptions are meant to avoid
BANNED = re.compile(r"\b(perfect for|great for|ideal for|adds? atmosphere|high[- ]quality"
                    r"|stunning|beautiful|amazing)\b", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shards")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    wanted = set()
    for p in sorted(glob.glob(os.path.join(a.shards, "shard_*.json"))):
        for f in json.load(open(p, encoding="utf-8")):
            wanted.add(f["family"])

    out, dupes, problems = {}, [], []
    for p in sorted(glob.glob(os.path.join(a.shards, "out_*.json"))):
        try:
            rows = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            problems.append(f"{os.path.basename(p)}: unreadable - {e}")
            continue
        for r in rows:
            fam = r.get("family")
            what, use = (r.get("what") or "").strip(), (r.get("use") or "").strip()
            if not fam or not what or not use:
                problems.append(f"{os.path.basename(p)}: incomplete entry {r!r:.80}")
                continue
            if fam in out:
                dupes.append(fam)
                continue
            if len(what) > WHAT_MAX:
                problems.append(f"{fam}: what is {len(what)} chars (max {WHAT_MAX})")
            if len(use) > USE_MAX:
                problems.append(f"{fam}: use is {len(use)} chars (max {USE_MAX})")
            if BANNED.search(what + " " + use):
                problems.append(f"{fam}: marketing language - {BANNED.search(what+' '+use).group(0)!r}")
            out[fam] = {"what": what, "use": use}

    missing = sorted(wanted - set(out))
    extra = sorted(set(out) - wanted)

    print(f"families expected : {len(wanted):,}")
    print(f"families described: {len(out):,}")
    if dupes:
        print(f"  duplicated      : {len(dupes)}  {dupes[:5]}")
    if missing:
        print(f"  MISSING         : {len(missing)}  {missing[:10]}")
    if extra:
        print(f"  not in any shard: {len(extra)}  {extra[:10]}")
    if problems:
        print(f"  problems        : {len(problems)}")
        for x in problems[:12]:
            print(f"      {x}")
    if not (missing or extra or dupes or problems):
        print("  all clean")

    json.dump(out, open(a.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0, sort_keys=True)
    print(f"\nwrote {a.out} ({os.path.getsize(a.out)/1024:,.0f} KB)")


if __name__ == "__main__":
    main()
