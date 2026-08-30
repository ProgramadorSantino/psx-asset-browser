#!/usr/bin/env python3
"""
build_browser.py - emit a single self-contained HTML browser for the PSX library.

Combines the Blender render manifest (thumbnails + triangle counts) with a walk
of the library to index models, textures and audio into one searchable page.
Thumbnails are embedded as base64 WebP so the file works offline by double-click.

    python build_browser.py <library dir> <thumbs dir> -o ASSET_BROWSER.html
"""
import argparse, base64, io, json, os, re, struct
from collections import defaultdict
from PIL import Image

MODEL_TH, TEX_TH = 232, 128


def b64(img, size, quality):
    im = img.copy()
    im.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    if im.mode not in ("RGBA", "RGB"):
        im = im.convert("RGBA")
    im.save(buf, "WEBP", quality=quality, method=4)
    return base64.b64encode(buf.getvalue()).decode()


def ogg_seconds(path):
    """Duration = last page's granule position / sample rate. No decoding needed."""
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
            i = head.find(b"\x01vorbis")
            if i < 0:
                return None
            rate = struct.unpack("<I", head[i + 12:i + 16])[0]
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(0, end - 65536))
            tail = f.read()
            j = tail.rfind(b"OggS")
            if j < 0 or not rate:
                return None
            gran = struct.unpack("<q", tail[j + 6:j + 14])[0]
            return round(gran / rate, 2)
    except Exception:
        return None


def wav_seconds(path):
    try:
        with open(path, "rb") as f:
            d = f.read(64)
            rate = struct.unpack("<I", d[24:28])[0]
            byte_rate = struct.unpack("<I", d[28:32])[0]
            return round((os.path.getsize(path) - 44) / byte_rate, 2) if byte_rate else None
    except Exception:
        return None


# folders that name an export format rather than a kind of asset
NOISE = {"Models", "Meshes", "Textures", "Audio", "other-formats", ".other-formats",
         "GLB", "GLB (recommended)", "FBX", "OBJ", "DAE", "OGG", "WAV",
         "BLEND (source)", "BLEND", "Sprites"}


# A bundle of many small sub-packs is listed as ONE pack whose categories are the
# sub-packs. Otherwise 17 folders of 5 assets each swamp the pack filter.
GROUPED = {"Mystery Bundle"}


def categorise(rel):
    """Pull a human category out of the pack's own folder layout."""
    parts = rel.split("/")
    pack = parts[0]
    if pack in GROUPED and len(parts) > 2:
        return pack, parts[1]
    after = [p for p in parts[1:-1] if p not in NOISE]
    if after:
        return pack, after[-1]
    # the big packs sort by an internal folder; the Mystery mini-packs are each a
    # single subject, so the pack name is the most useful category they have
    fallback = {"PSX Nature": "Nature", "PSX Tech": "Tech & Industrial",
                "PSX Bunkers": "Bunker & Military"}
    return pack, fallback.get(pack, pack)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lib")
    ap.add_argument("thumbs")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--relations", help="relations.json from build_relations.py")
    ap.add_argument("--descriptions", help="descriptions.json, keyed by family")
    ap.add_argument("--no-audio", action="store_true",
                    help="omit the audio index (for a build shared without the packs)")
    a = ap.parse_args()
    LIB = a.lib.replace("\\", "/")

    rel_data = json.load(open(a.relations, encoding="utf-8")) if a.relations else {}
    desc = json.load(open(a.descriptions, encoding="utf-8")) if a.descriptions else {}
    fam_of = rel_data.get("fam_of", {})
    fams = rel_data.get("families", {})
    goes = rel_data.get("goes_with", {})
    simil = rel_data.get("similar", {})

    man = {m["key"]: m for m in json.load(open(os.path.join(a.thumbs, "models.json"), encoding="utf-8"))}
    print(f"manifest: {len(man):,} rendered models")

    # ---- index every file once -------------------------------------------------
    glbs, fbxs, texs, auds = {}, {}, [], []
    for dp, _dn, fn in os.walk(LIB):
        for f in fn:
            p = os.path.join(dp, f).replace("\\", "/")
            rel = os.path.relpath(p, LIB).replace("\\", "/")
            e = os.path.splitext(f)[1].lower()
            stem = os.path.splitext(f)[0]
            if e == ".glb":
                glbs[rel] = stem
            elif e == ".fbx":
                fbxs.setdefault(stem.lower(), []).append(rel)
            elif e in (".png", ".jpg"):
                texs.append(rel)
            elif e in (".ogg", ".wav"):
                auds.append(rel)

    models = []
    for rel, stem in sorted(glbs.items()):
        key = rel[:-4].replace("/", "__")
        m = man.get(key)
        th = os.path.join(a.thumbs, key + ".png")
        if not os.path.exists(th):
            continue
        pack, cat = categorise(rel)
        fbx = fbxs.get(stem.lower(), [])
        dim = m["dim"] if m else [0, 0, 0]
        fam = fam_of.get(key, "")
        models.append(dict(
            n=stem, p=pack, c=cat, g=rel, k=key,
            f=fbx[0] if fbx else "",
            t=m["tris"] if m else 0, v=m["verts"] if m else 0,
            d=[round(x, 2) for x in dim],
            tx=[re.sub(r"\.\d{3}$", "", x) for x in (m["textures"] if m else [])][:6],
            fm=fam,
            va=[x for x in fams.get(fam, []) if x != key][:8],
            gw=goes.get(key, [])[:6],
            sm=simil.get(key, [])[:6],
            i=b64(Image.open(th), MODEL_TH, 80)))
    print(f"models: {len(models):,}")

    tex = []
    for rel in sorted(texs):
        pack = rel.split("/")[0]
        parts = rel.split("/")
        kind = "Normal" if "Normal" in rel else ("Color" if "Color" in rel else "Texture")
        try:
            im = Image.open(os.path.join(LIB, rel))
            w, h = im.size
            tex.append(dict(n=os.path.basename(rel), p=pack, c=kind, g=rel,
                            r=f"{w}x{h}", b=os.path.getsize(os.path.join(LIB, rel)),
                            i=b64(im, TEX_TH, 72)))
        except Exception:
            continue
    print(f"textures: {len(tex):,}")

    aud = []
    for rel in sorted(auds):
        parts = rel.split("/")
        pack = parts[0]
        if pack in GROUPED and len(parts) > 2:
            cat = parts[1]
        else:
            mid = [x for x in parts[1:-1] if x not in NOISE]
            cat = mid[-1] if mid else pack
        p = os.path.join(LIB, rel)
        secs = ogg_seconds(p) if rel.lower().endswith(".ogg") else wav_seconds(p)
        aud.append(dict(n=os.path.splitext(os.path.basename(rel))[0], p=pack, c=cat,
                        g=rel, s=secs or 0, b=os.path.getsize(p)))
    print(f"audio: {len(aud):,}")

    if a.no_audio:
        print("  (--no-audio: audio index omitted)")
        aud = []
    # descriptions are stored per family, not per model - one line covers all five
    # barrels, and repeating it 1,361 times would bloat the page for nothing
    used = {m["fm"] for m in models if m["fm"]}
    dmap = {k: v for k, v in desc.items() if k in used}
    print(f"descriptions: {len(dmap):,} families described "
          f"({sum(1 for m in models if m['fm'] in dmap):,}/{len(models):,} models covered)")
    data = json.dumps(dict(m=models, t=tex, a=aud, d=dmap), separators=(",", ":"))
    html = TEMPLATE.replace("/*__DATA__*/", data)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\nwrote {a.out}  ({os.path.getsize(a.out)/1024**2:,.1f} MB)")


TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PSX Asset Library</title><style>
:root{
  --void:#16191a; --concrete:#1e2223; --slab:#252a2b; --slab-hi:#2c3233;
  --steel:#39403f; --steel-hi:#586361;
  --bone:#d6d3c8; --ash:#8b918d; --dim:#666e6c;
  --rust:#c85a25; --hazard:#e0a92e; --combine:#6fa8bd;
  --mono:"Cascadia Mono","Consolas",ui-monospace,"DejaVu Sans Mono",monospace;
  --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--void);color:var(--bone);font:13px/1.5 var(--mono);
  -webkit-font-smoothing:antialiased}
::selection{background:var(--rust);color:#fff}

/* hazard stripe: the one piece of ornament, and it earns its place by marking
   the page head the way it marks a loading bay */
.stripe{height:5px;background:repeating-linear-gradient(-45deg,
  var(--hazard) 0 11px,#191d1e 11px 22px);flex:none}

#top{display:flex;align-items:baseline;gap:18px;padding:13px 20px 12px;
  background:var(--concrete);border-bottom:1px solid var(--steel);flex:none;flex-wrap:wrap}
#top h1{font-size:15px;margin:0;letter-spacing:.16em;text-transform:uppercase;font-weight:700}
#top h1 b{color:var(--rust)}
.stat{color:var(--dim);font-size:11px;letter-spacing:.08em}
.stat i{color:var(--hazard);font-style:normal}
#search{margin-left:auto;background:var(--void);border:1px solid var(--steel);
  color:var(--bone);font:12px var(--mono);padding:7px 11px;width:290px;letter-spacing:.04em}
#search:focus{outline:none;border-color:var(--rust);background:#121516}
#search::placeholder{color:var(--dim)}

#shell{display:flex;height:100%;min-height:0}
#side{width:252px;flex:none;background:var(--concrete);border-right:1px solid var(--steel);
  overflow:auto;padding:0 0 40px}
#main{flex:1;overflow:auto;padding:18px 22px 70px;min-width:0}

.tabs{display:flex;border-bottom:1px solid var(--steel)}
.tab{flex:1;padding:9px 4px;text-align:center;font-size:11px;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ash);cursor:pointer;border-bottom:2px solid transparent}
.tab:hover{color:var(--bone);background:var(--slab)}
.tab.on{color:var(--rust);border-bottom-color:var(--rust);background:var(--slab)}

.sec{padding:15px 14px 4px}
.lbl{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim);
  margin:0 0 8px;display:flex;justify-content:space-between;align-items:center}
.opt{display:flex;justify-content:space-between;gap:8px;padding:4px 7px;cursor:pointer;
  color:var(--ash);font-size:12px;border-left:2px solid transparent}
.opt:hover{background:var(--slab);color:var(--bone)}
.opt.on{background:var(--slab-hi);color:var(--bone);border-left-color:var(--rust)}
.opt .n{color:var(--dim);font-variant-numeric:tabular-nums;font-size:11px}
.opt.on .n{color:var(--hazard)}

/* SIGNATURE: triangle-budget profiler. Bars show how the currently visible set
   is distributed by triangle count; drag the handles to filter by poly budget.
   For a Unity scene the poly cost is the constraint that actually bites. */
#budget{padding:0 14px 16px}
#hist{display:flex;align-items:flex-end;gap:1px;height:52px;
  border-bottom:1px solid var(--steel);padding-bottom:0;cursor:ew-resize;position:relative}
#hist .bar{flex:1;background:var(--steel-hi);min-height:1px;transition:background .1s}
#hist .bar.in{background:var(--rust)}
#hist .bar:hover{background:var(--hazard)}
.range{display:flex;justify-content:space-between;font-size:10px;color:var(--dim);
  margin-top:5px;font-variant-numeric:tabular-nums}
.range b{color:var(--hazard);font-weight:400}
.reset{color:var(--combine);cursor:pointer;font-size:10px;letter-spacing:.08em}
.reset:hover{color:var(--bone)}

h2{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--hazard);
  font-weight:700;margin:26px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--steel);
  display:flex;justify-content:space-between;align-items:baseline}
h2:first-child{margin-top:0}
h2 span{color:var(--dim);font-size:10px;letter-spacing:.08em}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(152px,1fr));gap:11px}
.card{background:var(--slab);border:1px solid var(--steel);cursor:pointer;position:relative;
  transition:border-color .11s,background .11s}
.card:hover{border-color:var(--rust);background:var(--slab-hi)}
.card:focus-visible{outline:2px solid var(--combine);outline-offset:1px}
.th{height:118px;display:flex;align-items:center;justify-content:center;overflow:hidden;
  background:radial-gradient(ellipse at 50% 38%,#2f3637 0%,#1a1e1f 78%);position:relative}
.th img{max-width:96%;max-height:112px;display:block}
/* corner brackets: a viewport crop mark, not decoration for its own sake */
.th::before,.th::after{content:"";position:absolute;width:7px;height:7px;
  border:1px solid var(--steel-hi);opacity:.85}
.th::before{top:5px;left:5px;border-right:0;border-bottom:0}
.th::after{bottom:5px;right:5px;border-left:0;border-top:0}
.card:hover .th::before,.card:hover .th::after{border-color:var(--rust)}
.meta{padding:7px 8px 8px;border-top:1px solid var(--steel)}
.nm{font-size:11px;color:var(--bone);word-break:break-word;line-height:1.35;margin-bottom:3px}
.sub{font-size:10px;color:var(--dim);font-variant-numeric:tabular-nums;
  display:flex;justify-content:space-between;gap:6px}
.sub .t{color:var(--combine)}
.hi{background:var(--hazard);color:#191d1e}

.trow{display:flex;align-items:center;gap:11px;padding:6px 9px;border:1px solid transparent;
  border-bottom:1px solid #23282900;cursor:pointer}
.trow:hover{background:var(--slab);border-color:var(--steel)}
.trow img{width:40px;height:40px;object-fit:cover;background:#111;flex:none;
  border:1px solid var(--steel)}
.trow .g{flex:1;min-width:0}
.trow .g div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.trow .s{color:var(--dim);font-size:10px;font-variant-numeric:tabular-nums;flex:none}
.play{width:26px;height:26px;flex:none;border:1px solid var(--steel);background:var(--slab);
  color:var(--rust);cursor:pointer;font-size:10px;line-height:1;padding:0}
.play:hover{border-color:var(--rust);background:var(--slab-hi)}
.play.on{background:var(--rust);color:#fff;border-color:var(--rust)}
.wave{height:3px;background:var(--steel);margin-top:5px;position:relative;overflow:hidden}
.wave i{position:absolute;inset:0 100% 0 0;background:var(--rust)}

#empty{color:var(--dim);padding:40px 4px;font-size:12px}
#empty b{color:var(--hazard);font-weight:400}

#ov{position:fixed;inset:0;background:rgba(10,12,13,.88);display:none;z-index:60;
  overflow:auto;padding:32px 20px}
#ov.on{display:block}
#pan{max-width:940px;margin:0 auto;background:var(--concrete);
  border:1px solid var(--steel-hi);box-shadow:0 18px 60px rgba(0,0,0,.6)}
.phead{display:flex;align-items:baseline;gap:12px;padding:14px 20px;
  border-bottom:1px solid var(--steel);background:var(--slab)}
.phead h3{margin:0;font-size:14px;letter-spacing:.08em;color:var(--bone)}
.phead .x{margin-left:auto;color:var(--ash);cursor:pointer;font-size:18px;line-height:1;
  padding:0 4px;background:none;border:0}
.phead .x:hover{color:var(--rust)}
.pbody{display:grid;grid-template-columns:300px 1fr;gap:0}
.pimg{background:radial-gradient(ellipse at 50% 40%,#2f3637 0%,#141819 78%);
  display:flex;align-items:center;justify-content:center;padding:18px;
  border-right:1px solid var(--steel)}
.pimg img{max-width:100%;image-rendering:auto}
.pinfo{padding:16px 20px 20px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:4px 10px 4px 0;vertical-align:top}
th{color:var(--dim);font-weight:400;width:104px;font-size:11px;letter-spacing:.07em;
  text-transform:uppercase}
td{color:var(--bone);font-variant-numeric:tabular-nums;word-break:break-all}
.path{display:flex;gap:6px;align-items:center;margin:4px 0}
.path code{flex:1;background:var(--void);border:1px solid var(--steel);padding:5px 8px;
  font-size:11px;color:var(--combine);word-break:break-all}
.cp{border:1px solid var(--steel);background:var(--slab);color:var(--ash);font:10px var(--mono);
  padding:5px 9px;cursor:pointer;letter-spacing:.08em;flex:none}
.cp:hover{border-color:var(--rust);color:var(--bone)}
.cp.done{background:var(--rust);color:#fff;border-color:var(--rust)}
.tip{margin-top:14px;border-left:2px solid var(--hazard);background:#1a1e1f;
  padding:9px 13px;font:12px/1.6 var(--sans);color:var(--ash)}
.tip b{color:var(--bone);font-weight:600}
.tag{display:inline-block;border:1px solid var(--steel);color:var(--ash);font-size:10px;
  padding:1px 6px;margin:0 4px 4px 0;letter-spacing:.06em}

/* what the thing is, in plain words - the first thing you should read */
.what{font:15px/1.5 var(--sans);color:var(--bone);margin:0 0 7px}
.use{font:13px/1.55 var(--sans);color:var(--ash);margin:0 0 15px;
  border-left:2px solid var(--rust);padding-left:11px}
.rel{margin-top:16px}
.rel h4{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:var(--dim);
  font-weight:400;margin:0 0 7px;display:flex;gap:8px;align-items:baseline}
.rel h4 em{font-style:normal;font:11px var(--sans);color:var(--steel-hi);
  letter-spacing:0;text-transform:none}
.strip{display:flex;gap:7px;overflow-x:auto;padding-bottom:5px}
.strip::-webkit-scrollbar{height:6px}
.strip::-webkit-scrollbar-thumb{background:var(--steel)}
.rc{flex:none;width:74px;cursor:pointer;background:var(--slab);border:1px solid var(--steel);
  padding:0 0 4px}
.rc:hover{border-color:var(--rust);background:var(--slab-hi)}
.rc:focus-visible{outline:2px solid var(--combine);outline-offset:1px}
.rc img{width:100%;height:58px;object-fit:contain;display:block;
  background:radial-gradient(ellipse at 50% 40%,#2f3637 0%,#1a1e1f 80%)}
.rc span{display:block;font-size:9px;color:var(--ash);padding:4px 4px 0;line-height:1.25;
  word-break:break-word}
@media(max-width:900px){
  #shell{flex-direction:column}
  #side{width:auto;border-right:0;border-bottom:1px solid var(--steel);max-height:none}
  .pbody{grid-template-columns:1fr}
  .pimg{border-right:0;border-bottom:1px solid var(--steel)}
  #search{width:100%;margin-left:0}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<div class="stripe"></div>
<div id="top">
  <h1>PSX <b>//</b> Asset Library</h1>
  <span class="stat" id="hdr"></span>
  <input id="search" placeholder="search  ( / )" autocomplete="off">
</div>
<div id="shell">
  <div id="side">
    <div class="tabs">
      <div class="tab on" data-k="m">Models</div>
      <div class="tab" data-k="t">Textures</div>
      <div class="tab" data-k="a">Audio</div>
    </div>
    <div id="budget" hidden>
      <p class="lbl">Triangle budget <span class="reset" id="rst">reset</span></p>
      <div id="hist"></div>
      <div class="range"><span><b id="lo">0</b> tris</span><span><b id="hi2">0</b> tris</span></div>
    </div>
    <div class="sec"><p class="lbl">Pack</p><div id="packs"></div></div>
    <div class="sec"><p class="lbl">Category</p><div id="cats"></div></div>
  </div>
  <div id="main"></div>
</div>
<div id="ov"><div id="pan"></div></div>
<audio id="au"></audio>
<script>
const D = /*__DATA__*/;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = n => n.toLocaleString();
const kb = b => b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.round(b/1024)+' KB';
const dur = s => s ? Math.floor(s/60)+':'+String(Math.round(s%60)).padStart(2,'0') : '--:--';

let kind='m', q='', pack='', cat='', tlo=0, thi=Infinity, bins=[];
const rows = () => D[kind];

// triangle histogram is computed on everything except the budget filter itself,
// so dragging it never collapses the chart you are dragging on
function preBudget(){
  return rows().filter(r =>
    (!pack || r.p===pack) && (!cat || r.c===cat) && match(r));
}
function match(r){
  if(!q) return true;
  const info = r.fm ? (D.d||{})[r.fm] : null;
  const h = (r.n+' '+r.p+' '+r.c+' '+(r.tx?r.tx.join(' '):'')
             +' '+(info ? info.what+' '+info.use : '')).toLowerCase();
  return q.split(/\s+/).every(w => h.includes(w));
}
function visible(){
  return preBudget().filter(r => kind!=='m' || (r.t>=tlo && r.t<=thi));
}

function buildHist(){
  if(kind!=='m'){ $('#budget').hidden=true; return; }
  $('#budget').hidden=false;
  const set = preBudget(), N=34;
  const max = Math.max(1, ...D.m.map(r=>r.t));
  const lg = v => Math.log10(1+v)/Math.log10(1+max);
  bins = new Array(N).fill(0);
  set.forEach(r => { bins[Math.min(N-1, Math.floor(lg(r.t)*N))]++; });
  const peak = Math.max(1, ...bins);
  const loB = Math.floor(lg(tlo)*N), hiB = thi===Infinity ? N : Math.floor(lg(thi)*N);
  $('#hist').innerHTML = bins.map((v,i) =>
    `<div class="bar${i>=loB&&i<=hiB?' in':''}" style="height:${Math.max(2,v/peak*100)}%" `+
    `title="${fmt(Math.round(Math.pow(10,i/N*Math.log10(1+max))-1))} tris — ${v} models"></div>`).join('');
  $('#lo').textContent = fmt(tlo);
  $('#hi2').textContent = thi===Infinity ? fmt(max) : fmt(thi);
}
// drag across the histogram to set the budget window
(function(){
  const h=$('#hist'); let drag=null;
  const binAt = e => {
    const r=h.getBoundingClientRect();
    return Math.max(0, Math.min(33, Math.floor((e.clientX-r.left)/r.width*34)));
  };
  const val = b => Math.round(Math.pow(10, b/34*Math.log10(1+Math.max(1,...D.m.map(r=>r.t))))-1);
  h.addEventListener('pointerdown', e=>{ drag=binAt(e); h.setPointerCapture(e.pointerId); });
  h.addEventListener('pointermove', e=>{
    if(drag===null) return;
    const b=binAt(e); tlo=val(Math.min(drag,b)); thi=val(Math.max(drag,b)+1); render();
  });
  h.addEventListener('pointerup', ()=>drag=null);
  $('#rst').onclick = ()=>{ tlo=0; thi=Infinity; render(); };
})();

// A facet count must answer "how many would I get if I clicked this", so every
// other active filter applies - including the triangle budget. Leaving the
// budget out made the sidebar disagree with the grid.
function inBudget(r){ return kind!=='m' || (r.t>=tlo && r.t<=thi); }
function facets(){
  const cp = {}, cc = {};
  let pAll = 0, cAll = 0;
  rows().forEach(r=>{
    if(!match(r) || !inBudget(r)) return;
    if(!cat || r.c===cat){ cp[r.p]=(cp[r.p]||0)+1; pAll++; }
    if(!pack || r.p===pack){ cc[r.c]=(cc[r.c]||0)+1; cAll++; }
  });
  const opt=(v,n,on,f)=>`<div class="opt${on?' on':''}" data-f="${f}" data-v="${esc(v)}">`+
    `<span>${esc(v||'All')}</span><span class="n">${fmt(n)}</span></div>`;
  $('#packs').innerHTML = opt('', pAll, !pack, 'p') +
    Object.keys(cp).sort().map(k=>opt(k,cp[k],pack===k,'p')).join('');
  $('#cats').innerHTML = opt('', cAll, !cat, 'c') +
    Object.entries(cc).sort((a,b)=>b[1]-a[1]).map(([k,v])=>opt(k,v,cat===k,'c')).join('');
}

function hl(s){
  if(!q) return esc(s);
  let out=esc(s);
  q.split(/\s+/).filter(Boolean).forEach(w=>{
    out = out.replace(new RegExp('('+w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'),'<span class="hi">$1</span>');
  });
  return out;
}

function render(){
  facets(); buildHist();
  const v = visible(), main=$('#main');
  $('#hdr').innerHTML = `<i>${fmt(D.m.length)}</i> models &nbsp;·&nbsp; <i>${fmt(D.t.length)}</i> textures `+
    `&nbsp;·&nbsp; <i>${fmt(D.a.length)}</i> audio &nbsp;·&nbsp; showing <i>${fmt(v.length)}</i>`;
  if(!v.length){
    main.innerHTML = `<div id="empty">No assets match <b>${esc(q||'this filter')}</b>.<br>`+
      `Clear the search or pick <b>All</b> above.</div>`; return;
  }
  const groups={};
  v.forEach(r=>(groups[r.c]=groups[r.c]||[]).push(r));
  const order = Object.keys(groups).sort((a,b)=>groups[b].length-groups[a].length);
  main.innerHTML = order.map(g=>{
    const items = groups[g];
    const body = kind==='a'
      ? items.map(r=>audRow(r)).join('')
      : `<div class="${kind==='t'?'grid':'grid'}">`+items.map(r=>card(r)).join('')+`</div>`;
    const extra = kind==='m'
      ? `<span>${fmt(items.reduce((s,r)=>s+r.t,0))} tris total</span>` : `<span>${fmt(items.length)}</span>`;
    return `<h2>${esc(g)} ${extra}</h2>${body}`;
  }).join('');
}

function card(r){
  const i = rows().indexOf(r);
  if(kind==='t') return `<div class="card" tabindex="0" data-i="${i}">`+
    `<div class="th"><img loading="lazy" src="data:image/webp;base64,${r.i}" alt=""></div>`+
    `<div class="meta"><div class="nm">${hl(r.n)}</div>`+
    `<div class="sub"><span>${r.r}</span><span class="t">${kb(r.b)}</span></div></div></div>`;
  return `<div class="card" tabindex="0" data-i="${i}">`+
    `<div class="th"><img loading="lazy" src="data:image/webp;base64,${r.i}" alt=""></div>`+
    `<div class="meta"><div class="nm">${hl(r.n)}</div>`+
    `<div class="sub"><span class="t">${fmt(r.t)} tri</span>`+
    `<span>${r.d[0]}&times;${r.d[1]}&times;${r.d[2]}</span></div></div></div>`;
}

function audRow(r){
  const i = rows().indexOf(r);
  return `<div class="trow" data-i="${i}">`+
    `<button class="play" data-play="${i}" aria-label="Play ${esc(r.n)}">&#9654;</button>`+
    `<div class="g"><div>${hl(r.n)}</div><div class="wave"><i></i></div></div>`+
    `<span class="s">${dur(r.s)}</span><span class="s">${kb(r.b)}</span></div>`;
}

// ---- detail ---------------------------------------------------------------
function open(r){
  const isM = kind==='m', isT = kind==='t';
  const paths = isM
    ? [['FBX — import this into Unity', r.f],['GLB — web / glTF', r.g]].filter(x=>x[1])
    : [[isT?'Texture':'Audio', r.g]];
  const rowsHtml = isM ? `
      <tr><th>Pack</th><td>${esc(r.p)}</td></tr>
      <tr><th>Category</th><td>${esc(r.c)}</td></tr>
      <tr><th>Triangles</th><td>${fmt(r.t)}</td></tr>
      <tr><th>Vertices</th><td>${fmt(r.v)}</td></tr>
      <tr><th>Size (m)</th><td>${r.d[0]} &times; ${r.d[1]} &times; ${r.d[2]}</td></tr>
      <tr><th>Textures</th><td>${r.tx.length?r.tx.map(t=>`<span class="tag">${esc(t)}</span>`).join(''):'<span style="color:var(--dim)">embedded / none</span>'}</td></tr>`
    : isT ? `
      <tr><th>Pack</th><td>${esc(r.p)}</td></tr>
      <tr><th>Type</th><td>${esc(r.c)} map</td></tr>
      <tr><th>Resolution</th><td>${r.r}</td></tr>
      <tr><th>File size</th><td>${kb(r.b)}</td></tr>` : `
      <tr><th>Pack</th><td>${esc(r.p)}</td></tr>
      <tr><th>Category</th><td>${esc(r.c)}</td></tr>
      <tr><th>Length</th><td>${dur(r.s)}</td></tr>
      <tr><th>File size</th><td>${kb(r.b)}</td></tr>`;
  const tip = isM
    ? `<b>Import:</b> drag the FBX into Unity. Set every texture to <b>Filter Mode: Point</b> —
       bilinear filtering smears 256px art and loses the PSX look. Leave mesh compression off;
       these are already low-poly.`
    : isT ? `<b>Import:</b> Filter Mode <b>Point</b>, Compression <b>None</b>, Max Size <b>${r.r.split('x')[0]}</b>.
       Going above the source resolution only interpolates.`
    : `<b>Import:</b> Unity reads .ogg natively. Use <b>Decompress On Load</b> for short SFX
       and <b>Streaming</b> for tracks over ~30 s.`;
  const info = isM ? (D.d||{})[r.fm] : null;
  const blurb = info ? `<p class="what">${esc(info.what)}</p>
       <p class="use">${esc(info.use)}</p>` : '';
  const rels = isM ? [
      ['Variants', r.va, 'the same thing in another flavour'],
      ['Goes with', r.gw, 'shares textures, so built for the same scene'],
      ['Looks like', r.sm, 'similar shape and shading'],
    ].filter(x => x[1] && x[1].length).map(([t, ks, why]) => `
      <div class="rel"><h4>${t} <span style="color:var(--hazard)">${ks.length}</span>
        <em>${why}</em></h4>
        <div class="strip">${ks.map(k => relCard(k)).filter(Boolean).join('')}</div></div>`).join('')
    : '';
  $('#pan').innerHTML = `
    <div class="phead"><h3>${esc(r.n)}</h3><span class="stat">${esc(r.p)}</span>
      <button class="x" aria-label="Close">&times;</button></div>
    <div class="pbody">
      ${r.i?`<div class="pimg"><img src="data:image/webp;base64,${r.i}" alt="${esc(r.n)}"></div>`:''}
      <div class="pinfo">${blurb}<table>${rowsHtml}</table>
        ${!isM&&kind==='a'?`<div class="path"><audio controls preload="none" style="width:100%"
             src="${esc(r.g).replace(/#/g,'%23')}"></audio></div>`:''}
        <p class="lbl" style="margin:16px 0 6px">Path</p>
        ${paths.map(([k,p])=>`<div class="path"><code>${esc(p)}</code>
          <button class="cp" data-copy="${esc(p)}">Copy</button></div>`).join('')}
        <div class="tip">${tip}</div>
        ${rels}
      </div></div>`;
  $('#ov').classList.add('on');
  $('#pan').scrollTop = 0;
  $('#pan').querySelector('.x').onclick = close;
}
const close = () => $('#ov').classList.remove('on');

// models addressed by their render key, so a related item can be opened directly
const BY_KEY = {};
D.m.forEach(m => { BY_KEY[m.k] = m; });
function relCard(k){
  const m = BY_KEY[k];
  if(!m) return '';
  return `<div class="rc" tabindex="0" data-go="${esc(k)}" title="${esc(m.n)} - ${fmt(m.t)} tri">
    <img loading="lazy" src="data:image/webp;base64,${m.i}" alt="">
    <span>${esc(m.n)}</span></div>`;
}

// ---- events ---------------------------------------------------------------
$('#main').addEventListener('click', e=>{
  const pb = e.target.closest('[data-play]');
  if(pb){ e.stopPropagation(); playAt(+pb.dataset.play, pb); return; }
  const c = e.target.closest('[data-i]');
  if(c) open(rows()[+c.dataset.i]);
});
$('#ov').addEventListener('keydown', e=>{
  const go = e.target.closest('[data-go]');
  if(go && (e.key==='Enter'||e.key===' ')){ e.preventDefault();
    const m = BY_KEY[go.dataset.go]; if(m){ kind='m'; open(m); } }
});
$('#main').addEventListener('keydown', e=>{
  const c = e.target.closest('[data-i]');
  if(c && (e.key==='Enter'||e.key===' ')){ e.preventDefault(); open(rows()[+c.dataset.i]); }
});
$('#side').addEventListener('click', e=>{
  const t = e.target.closest('.tab');
  if(t){ kind=t.dataset.k; pack=cat=''; tlo=0; thi=Infinity;
    document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));
    $('#main').scrollTop=0; render(); return; }
  const o = e.target.closest('.opt');
  if(o){ if(o.dataset.f==='p') pack=o.dataset.v; else cat=o.dataset.v; render(); }
});
$('#ov').addEventListener('click', e=>{
  const go = e.target.closest('[data-go]');
  if(go){ const m = BY_KEY[go.dataset.go]; if(m){ kind='m'; open(m); } return; }
  if(e.target.id==='ov') close();
  const b = e.target.closest('[data-copy]');
  if(b){ navigator.clipboard.writeText(b.dataset.copy).then(()=>{
    b.textContent='Copied'; b.classList.add('done');
    setTimeout(()=>{b.textContent='Copy'; b.classList.remove('done');},1100); }); }
});
$('#search').addEventListener('input', e=>{ q=e.target.value.trim().toLowerCase(); render(); });
addEventListener('keydown', e=>{
  if(e.key==='Escape') close();
  if(e.key==='/' && document.activeElement!==$('#search')){ e.preventDefault(); $('#search').focus(); }
});

// audio: files are referenced relatively, so the browser must sit beside the packs
let cur=null;
function playAt(i, btn){
  const r = D.a[i], au = $('#au');
  if(cur===btn){ au.pause(); btn.classList.remove('on'); btn.innerHTML='&#9654;'; cur=null; return; }
  if(cur){ cur.classList.remove('on'); cur.innerHTML='&#9654;'; }
  au.src = r.g.replace(/#/g,'%23'); au.play().catch(()=>{
    btn.title='Could not play - keep this file in the library folder';
  });
  btn.classList.add('on'); btn.innerHTML='&#9632;'; cur=btn;
  au.onended = ()=>{ btn.classList.remove('on'); btn.innerHTML='&#9654;'; cur=null; };
}

render();
</script></body></html>"""


if __name__ == "__main__":
    main()
