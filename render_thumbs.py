"""
render_thumbs.py - batch-render GLB models to transparent PNG thumbnails.

Run INSIDE Blender, once, for the whole library - starting Blender per model
would cost more in startup than in rendering:

    blender --background --factory-startup --python render_thumbs.py -- \
        <library dir> <out dir> [--size 256] [--limit N] [--manifest file.json]

Each model is imported, framed by its own bounding box at a fixed 3/4 angle so
every thumbnail reads at the same apparent size, rendered on a transparent
background, then purged before the next one.

Also records triangle counts, material and dimension data into a JSON manifest -
the numbers that actually matter when picking an asset for a Unity scene.
"""
import bpy, sys, os, json, math, time
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(argv) < 2:
    raise SystemExit("usage: ... -- <library dir> <out dir> [--size N] [--limit N]")
SRC, OUT = argv[0], argv[1]
SIZE = int(argv[argv.index("--size") + 1]) if "--size" in argv else 256
LIMIT = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 0
MANIFEST = argv[argv.index("--manifest") + 1] if "--manifest" in argv else os.path.join(OUT, "models.json")

os.makedirs(OUT, exist_ok=True)


def wipe():
    """Remove everything and purge orphans - otherwise memory climbs over 1000+ imports."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_scene():
    sc = bpy.context.scene
    # EEVEE: quality is fine for flat PSX-style textures and it is ~50x faster than Cycles
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    sc.render.resolution_x = sc.render.resolution_y = SIZE
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.compression = 90
    if hasattr(sc.render, "use_high_quality_normals"):
        sc.render.use_high_quality_normals = True
    try:
        sc.eevee.taa_render_samples = 16
    except AttributeError:
        pass
    # Blender 4+ defaults to the AgX view transform, which is built for filmic
    # photography and crushes flat unlit texture art to near-black. Asset
    # thumbnails want the raw colours the texture actually contains.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    # These packs are authored for in-game lighting: the concrete albedo peaks at
    # 79/255. A faithful render is nearly black in a browser grid, so lift it -
    # a thumbnail exists to identify the prop, not to be colour-accurate.
    sc.view_settings.exposure = 1.6
    sc.display_settings.display_device = "sRGB"

    # world: soft ambient so unlit faces are not pure black
    w = bpy.data.worlds.new("W")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.32, 0.34, 0.38, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.35

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"          # ortho keeps every thumbnail visually consistent
    cam = bpy.data.objects.new("Cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam

    key = bpy.data.lights.new("Key", "SUN")
    key.energy = 4.5
    key.angle = math.radians(25)
    ko = bpy.data.objects.new("Key", key)
    sc.collection.objects.link(ko)
    ko.rotation_euler = (math.radians(50), 0, math.radians(40))

    fill = bpy.data.lights.new("Fill", "SUN")
    fill.energy = 2.0
    fo = bpy.data.objects.new("Fill", fill)
    sc.collection.objects.link(fo)
    fo.rotation_euler = (math.radians(65), 0, math.radians(-115))
    return cam


def frame(cam, objs):
    """Aim an ortho camera down a fixed 3/4 direction, sized to the bounding box."""
    pts = []
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    if not pts:
        return None
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) / 2
    dim = hi - lo
    radius = max(dim.length / 2, 1e-4)

    yaw, pitch = math.radians(35), math.radians(24)
    d = Vector((math.cos(pitch) * math.sin(yaw), -math.cos(pitch) * math.cos(yaw), math.sin(pitch)))
    cam.location = ctr + d * (radius * 4 + 1)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    # size to the box's projected footprint so thin/long props still fill the tile
    right = d.cross(Vector((0, 0, 1)))
    right = right.normalized() if right.length > 1e-6 else Vector((1, 0, 0))
    up = right.cross(d).normalized()
    ext = max(max(abs((p - ctr).dot(right)) for p in pts),
              max(abs((p - ctr).dot(up)) for p in pts))
    cam.data.ortho_scale = max(ext * 2.18, 1e-3)   # margin so nothing clips the edge
    return dict(dim=[round(v, 4) for v in dim], radius=round(radius, 4))


def stats(objs):
    tris = verts = 0
    mats, tex = set(), set()
    for o in objs:
        if o.type != "MESH":
            continue
        me = o.data
        verts += len(me.vertices)
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        for m in me.materials:
            if not m:
                continue
            mats.add(m.name)
            if m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image:
                        tex.add(os.path.basename(n.image.name))
    return tris, verts, sorted(mats), sorted(tex)


glbs = []
for dp, _dn, fn in os.walk(SRC):
    for f in sorted(fn):
        if f.lower().endswith(".glb"):
            glbs.append(os.path.join(dp, f))
glbs.sort()
if LIMIT:
    glbs = glbs[:LIMIT]

# incremental: keep thumbnails that already exist so merging a second bundle
# only pays for the models it actually added
prev = {}
if os.path.exists(MANIFEST) and "--force" not in argv:
    try:
        prev = {m["key"]: m for m in json.load(open(MANIFEST, encoding="utf-8"))}
    except Exception:
        prev = {}
    todo = [g for g in glbs
            if not os.path.exists(os.path.join(
                OUT, os.path.relpath(g, SRC).replace("\\", "/")[:-4].replace("/", "__") + ".png"))]
    print(f"[thumbs] {len(glbs)-len(todo)} already rendered, {len(todo)} new", flush=True)
    glbs = todo

print(f"[thumbs] {len(glbs)} models -> {OUT} @ {SIZE}px", flush=True)
out, t0, fails = [], time.time(), 0

for i, path in enumerate(glbs, 1):
    rel = os.path.relpath(path, SRC).replace("\\", "/")
    key = rel[:-4].replace("/", "__")
    dest = os.path.join(OUT, key + ".png")
    try:
        wipe()
        cam = setup_scene()
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        objs = [o for o in bpy.data.objects if o not in before]
        geo = frame(cam, objs)
        if geo is None:
            raise RuntimeError("no mesh data")
        tris, verts, mats, tex = stats(objs)
        bpy.context.scene.render.filepath = dest
        bpy.ops.render.render(write_still=True)
        out.append(dict(key=key, rel=rel, tris=tris, verts=verts,
                        materials=mats, textures=tex, **geo))
    except Exception as e:
        fails += 1
        print(f"  !! {rel}: {type(e).__name__}: {e}", flush=True)
    if i % 25 == 0 or i == len(glbs):
        el = time.time() - t0
        print(f"  [{i}/{len(glbs)}] {el:.0f}s  {el/i:.2f}s/model  "
              f"eta {(len(glbs)-i)*el/i/60:.1f}min  fails={fails}", flush=True)

done = {r["key"] for r in out}
out += [v for k, v in prev.items() if k not in done]
with open(MANIFEST, "w", encoding="utf-8") as fh:
    json.dump(out, fh)
print(f"[thumbs] done: {len(out)} rendered, {fails} failed, {time.time()-t0:.0f}s", flush=True)
