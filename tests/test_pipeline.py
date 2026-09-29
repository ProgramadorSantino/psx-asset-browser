"""Tests for the pure parts of the pipeline - no library, Blender or browser needed.

    python -m unittest discover tests
"""
import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from packs import categorise, family_from_name, model_key, propose_family  # noqa: E402
from build_relations import assign_families  # noqa: E402
from build_browser import pick_fbx  # noqa: E402


class Families(unittest.TestCase):
    def test_numbered_variants_share_a_family(self):
        self.assertEqual(family_from_name("metal_barrel_hr_1"), "metal_barrel_hr")
        self.assertEqual(family_from_name("metal_barrel_hr_4_1"), "metal_barrel_hr")

    def test_a_number_does_not_change_the_family(self):
        # the old rule put these two in different families
        self.assertEqual(family_from_name("ammo_box_mp"), family_from_name("ammo_box_mp_1"))

    def test_pack_suffix_is_kept(self):
        # pipe is a 3 m pipe run, pipe_mx a 42 cm offcut - not variants of each other
        self.assertNotEqual(family_from_name("pipe_1"), family_from_name("pipe_mx_1"))

    def test_a_middle_number_is_part_of_the_name(self):
        # lamp_1 is a caged strip light, lamp_2 a wall lamp
        self.assertNotEqual(family_from_name("lamp_1_off"), family_from_name("lamp_2_off"))

    def test_proposal_prefers_a_described_family(self):
        self.assertEqual(propose_family("ammo_box_mp", {"ammo_box_mp", "ammo_box"}), "ammo_box_mp")
        # its own family has no description yet, the legacy one does: keep showing it
        self.assertEqual(propose_family("brick_hr", {"brick"}), "brick")
        self.assertEqual(propose_family("brick_hr", set()), "brick_hr")

    def test_every_described_family_can_still_be_reached(self):
        with open(os.path.join(ROOT, "descriptions.json"), encoding="utf-8") as fh:
            desc = json.load(fh)
        unreachable = [k for k in desc if family_from_name(k + "_1") != k]
        self.assertEqual(unreachable, [])


class FamilyStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "families.json")

    def models(self, *rels):
        return [dict(key=model_key(r), rel=r) for r in rels]

    def test_assignments_are_written_and_then_kept(self):
        ms = self.models("PSX Tech/GLB/metal_barrel_hr_1.glb", "Mega/GLB/metal_barrel_mp_1.glb")
        first = assign_families(ms, self.path, {})
        self.assertEqual(sorted(set(first.values())), ["metal_barrel_hr", "metal_barrel_mp"])

        # merge the two drums by hand, as a user would in families.json
        with open(self.path, encoding="utf-8") as fh:
            store = json.load(fh)
        store[model_key("Mega/GLB/metal_barrel_mp_1.glb")] = "metal_barrel_hr"
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(store, fh)

        ms += self.models("Mega/GLB/metal_barrel_mp_2.glb", "Mega/GLB/crate_mp_1.glb")
        again = assign_families(ms, self.path, {})
        self.assertEqual(again[model_key("Mega/GLB/metal_barrel_mp_1.glb")], "metal_barrel_hr")
        # a new model joins the family its siblings were given, not the one its name suggests
        self.assertEqual(again[model_key("Mega/GLB/metal_barrel_mp_2.glb")], "metal_barrel_hr")
        # and a model with no siblings is proposed one from its name
        self.assertEqual(again[model_key("Mega/GLB/crate_mp_1.glb")], "crate_mp")

    def test_same_name_in_two_packs_are_two_models(self):
        ms = self.models("PSX Tech/GLB/chair_1.glb", "Mystery Bundle/Garage/chair_1.glb")
        fam = assign_families(ms, self.path, {})
        self.assertEqual(len(fam), 2)


class Categories(unittest.TestCase):
    def test_grouped_bundle_uses_sub_pack(self):
        self.assertEqual(categorise("Mystery Bundle/Retro Toys/GLB/toy_brick_1.glb"),
                         ("Mystery Bundle", "Retro Toys"))

    def test_export_folders_are_skipped(self):
        self.assertEqual(categorise("PSX Mega Pack/Props/Kitchen/GLB (recommended)/cup.glb"),
                         ("PSX Mega Pack", "Kitchen"))

    def test_fallback_category(self):
        self.assertEqual(categorise("PSX Nature/Models/GLB/tree_1.glb"), ("PSX Nature", "Nature"))
        self.assertEqual(categorise("Other Pack/GLB/x.glb"), ("Other Pack", "Other Pack"))


class Fbx(unittest.TestCase):
    def test_same_name_in_another_pack_is_not_a_match(self):
        self.assertEqual(pick_fbx("PSX Tech/Models/GLB/chair_1.glb",
                                  ["Mystery Bundle/Garage/FBX/chair_1.fbx"]), "")

    def test_prefers_the_sibling_export_folder(self):
        got = pick_fbx("PSX Tech/Models/GLB/chair_1.glb",
                       ["Mystery Bundle/Garage/FBX/chair_1.fbx",
                        "PSX Tech/Extra/FBX/chair_1.fbx",
                        "PSX Tech/Models/FBX/chair_1.fbx"])
        self.assertEqual(got, "PSX Tech/Models/FBX/chair_1.fbx")


if __name__ == "__main__":
    unittest.main()
