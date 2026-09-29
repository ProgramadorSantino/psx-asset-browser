"""
packs.py - everything that is specific to Pizza Doggy's PSX packs, in one place.

This tool is built for those packs and nothing else. The folder names below, the
bundles that get grouped and the naming scheme all come from how they ship. If a
pack update renames a folder, this is the file to change.
"""
import os, re

# folders that name an export format rather than a kind of asset
NOISE = {"Models", "Meshes", "Textures", "Audio", "other-formats", ".other-formats",
         "GLB", "GLB (recommended)", "FBX", "OBJ", "DAE", "OGG", "WAV",
         "BLEND (source)", "BLEND", "Sprites"}

# A bundle of many small sub-packs is listed as ONE pack whose categories are the
# sub-packs. Otherwise 17 folders of 5 assets each swamp the pack filter.
GROUPED = {"Mystery Bundle"}

# The big packs sort by an internal folder; when a file sits outside one, the
# pack's subject is the most useful category it has.
FALLBACK_CATEGORY = {"PSX Nature": "Nature", "PSX Tech": "Tech & Industrial",
                     "PSX Bunkers": "Bunker & Military"}


def categorise(rel):
    """(pack, category) for a library-relative path, from the pack's own folders."""
    parts = rel.split("/")
    pack = parts[0]
    if pack in GROUPED and len(parts) > 2:
        return pack, parts[1]
    after = [p for p in parts[1:-1] if p not in NOISE]
    if after:
        return pack, after[-1]
    return pack, FALLBACK_CATEGORY.get(pack, pack)


def model_key(rel):
    """A model's key: its GLB path with the separators flattened. Unique across the
    library, unlike its file name, and the name its thumbnail is rendered to."""
    return rel[:-4].replace("/", "__")


# ---- families ----------------------------------------------------------------
# A family is the set of models that are the same thing in another flavour. Each
# model's family is assigned once and stored in families.json; the name is only
# used to PROPOSE a family for a model that has not been assigned one yet.
#
# The proposal strips trailing numbers and nothing else: metal_barrel_hr_1 ..
# metal_barrel_hr_4_1 are one family. It deliberately keeps the pack suffix
# (_hr, _mp, _mx...), because the same stem often names a different object in
# another pack - pipe is a 3 m pipe run, pipe_mx a 42 cm offcut. Merging families
# across packs is a decision made in families.json, not a guess made here.

TRAIL_NUM = re.compile(r"(?:_\d+)+$")

# The rule the families in descriptions.json were first written against. It
# stripped a pack suffix only when no number followed it, so ammo_box_mp and
# ammo_box_mp_1 landed in different families. Kept only so a model whose correct
# family has no description yet can fall back to the one it used to show.
LEGACY_PACK_CODE = re.compile(r"_(?:hr|mp|mx|mh|hm|cx|dx|rg|rtx|emx|emh|bnk|ufx|sfx)\b", re.I)


def _tidy(s):
    return re.sub(r"__+", "_", s).strip("_")


def family_from_name(name):
    s = name.lower()
    return _tidy(TRAIL_NUM.sub("", s)) or s


def legacy_family(name):
    s = LEGACY_PACK_CODE.sub("", name.lower())
    return _tidy(TRAIL_NUM.sub("", s)) or name.lower()


def propose_family(name, known=()):
    """Family for a model with no stored assignment. `known` holds family keys
    that already mean something (described, or assigned to other models): if the
    name's own family is new but the legacy rule lands on a known one, use that,
    so an existing description keeps showing."""
    fam = family_from_name(name)
    if fam in known:
        return fam
    old = legacy_family(name)
    return old if old in known else fam


def model_name(rel):
    return os.path.splitext(os.path.basename(rel))[0]
