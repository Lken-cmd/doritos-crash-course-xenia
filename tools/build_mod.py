"""Build the "4 players" mod for Doritos Crash Course (XBLA, 58410A71).

The game draws each player with the console's Xbox avatar (XAVT resources),
which Xenia cannot provide, so the runners are invisible. The game also
ships the stand-in avatar its PC build used: a Cal3D mesh, skeleton and all
animations under data/art/_avatar. This script points every avatar slot at
that model as a boned model (BNMD) instead, with a different shirt colour
per controller, and adds the face textures and shaders the Xbox data lacks.

usage: python build_mod.py <game package or .zip> <out_dir> [<title update>]

Writes <out_dir>/game/ (run default.xex in Xenia) and <out_dir>/preview/.
With a title update (tu00000002_00000000), also writes <out_dir>/update/:
the update's files with its patch.pak modded the same way. The update's
patch.pak overrides data.pak, so the mod is re-applied on top of the
update's newer templates and dummymodel.cfg. Install it with
install_content.py --override-dir <out_dir>/update.

default.xex itself is untouched. In multiplayer the game shows each
player's avatar on helicopter billboards, rendered live into textures that
come out as garbage in Xenia; the build points those billboards at
pictures of the stand-in rendered here instead (see README).
"""
import argparse
import io
import os
import struct

from PIL import Image

import cal3d
import hidden_skin
import lua51
import make_textures
import pose
import render
import stfs
import tongaspak
import wbr
from avatar import AVATAR_DIR, BODY, FACE_GROUPS, FACE_TEX_SIZE, SUBMESH_SHADERS, body_name, textures

TEMPLATES = "data/templates"

# Xbox avatar resource name (XAVT:<name>) -> stand-in model.
# File-backed resources are looked up by path (template Name == file path),
# so every look is a real .cfg in _avatar/ with its own .mat.txt.
CREDITS = ["fojo", "benja", "carter", "chungi", "erich", "fco", "jean", "mike",
           "rena", "torrent"]


def res(name):
    """Resource name (as templates and .mat.txt files use it) of a file in AVATAR_DIR."""
    return "_avatar/" + name


def player_cfg(look):
    return res(f"player{look}.cfg")


def credits_cfg(look):
    return res(f"credits{look}.cfg")


AVATAR_TO_MODEL = {f"gamepad{i}": player_cfg(i + 1) for i in range(4)}
AVATAR_TO_MODEL.update({f"custom{i}": player_cfg(i + 1) for i in range(4)})
AVATAR_TO_MODEL.update({"random": player_cfg(1), "default": player_cfg(1)})
AVATAR_TO_MODEL.update({f"credits/{n}": credits_cfg(i % 4 + 1) for i, n in enumerate(CREDITS)})

# Every stand-in model file: cfg path -> (look, source cfg).
MODELS = {}
for _look in range(1, 5):
    MODELS[player_cfg(_look)] = (_look, "dummymodel.cfg")
    MODELS[credits_cfg(_look)] = (_look, "creditsmodel.cfg")

# Multiplayer billboards: player N's helicopter carries shader
# rtt/billboard<N>/pose_<K>, normally a live render of the avatar. Each pose
# gets a picture of the stand-in in a frame of one of its animations:
# (animation, point in it from 0 to 1, turn towards the camera in degrees).
# The 256x256 picture is stretched over a 4:3 quad, hence the squash.
BILLBOARD_POSES = {1: ("rope_idle", 0.5, 0), 2: ("rope_climb_up", 0.3, 0),
                   3: ("finish_happy_01_idle", 0.5, 90), 4: ("finish_happy_dance", 0.5, 90)}
BILLBOARD_SIZE = 256
BILLBOARD_SQUASH = 0.75

# Strings blanked in unistrings.wbr (LocalizedText: u32 length + UTF-16LE).
# Xenia has no Xbox LIVE profile, so the results screen always shows this.
BLANK_STRINGS = ["A gamer profile connected to Xbox LIVE is required to view the leaderboard."]
POSTING_GLOBAL = b"postingGameInLive"


def load_package(src):
    """{path: bytes} of an STFS package's files (or of the package in a .zip)."""
    with stfs.extracted(src) as path, stfs.Stfs(path) as pkg:
        return pkg.files()


def normalize_face_uvs(mesh):
    """Map each face group's UV range onto 0..1; return original-square rects."""
    rects = {}
    for name, ids in FACE_GROUPS.items():
        uvs = [uv for i in ids for v in mesh["submeshes"][i]["verts"] for uv in v["uv"]]
        u0, u1 = min(u for u, _ in uvs), max(u for u, _ in uvs)
        v0, v1 = min(v for _, v in uvs), max(v for _, v in uvs)
        for i in ids:
            for v in mesh["submeshes"][i]["verts"]:
                v["uv"] = [((u - u0) / (u1 - u0), (w - v0) / (v1 - v0)) for u, w in v["uv"]]
        w, h = FACE_TEX_SIZE[name]
        rects[name] = ((0 - u0) / (u1 - u0) * w, (0 - v0) / (v1 - v0) * h,
                       (1 - u0) / (u1 - u0) * w, (1 - v0) / (v1 - v0) * h)
    return rects


def billboard_name(n, k):
    return f"billboard_p{n}_{k}"


def materials(look):
    """Shader names per submesh, in .mat.txt order (see avatar.textures)."""
    return [res(s) for s in SUBMESH_SHADERS] + [res(body_name(look))]


def mat_txt(look):
    return ("\n".join(materials(look)) + "\nendmats\n").encode()


def blank_strings(data):
    for s in BLANK_STRINGS:
        old = struct.pack("<I", len(s)) + s.encode("utf-16-le")
        if data.count(old) != 1:
            raise ValueError(f"string not found exactly once: {s!r}")
        data = data.replace(old, struct.pack("<I", 1) + " ".encode("utf-16-le"))
    return data


def to_model_ref(ref):
    """XAVT:<name> -> BNMD:<cfg path>; anything else unchanged."""
    if ref.startswith("XAVT:") and ref[5:] in AVATAR_TO_MODEL:
        return "BNMD:" + AVATAR_TO_MODEL[ref[5:]]
    return ref


def warn_unconverted(where, refs):
    left = sorted({r for r in refs if r.startswith("XAVT:")})
    if left:
        print(f"  WARNING: {where} still uses Xbox avatars (invisible in Xenia): {left}")


def build_templates(read_tpl, bbox):
    out = {}

    shader = read_tpl("shader.wbr")
    for n in range(1, 5):
        shader.clone("props/umbrella", res(body_name(n)),
                     MultilayerDiffuse=res(body_name(n) + ".jpg"), Culling=0)
    for name in FACE_GROUPS:
        shader.clone("env/crowd_02", res(name), MultilayerDiffuse=res(name + ".png"),
                     Culling=0, AlphaTest=128)
    for n in range(1, 5):
        for k in BILLBOARD_POSES:
            key = f"rtt/billboard{n}/pose_{k:03d}"
            layers = list(shader.record(key)[1][shader.field_index("LayersDiffuseName")])
            layers[layers.index(key)] = res(billboard_name(n, k) + ".png")
            shader.edit(key, LayersDiffuseName=layers, AlphaTest=128)
    out["shader.wbr"] = shader

    texture = read_tpl("texture.wbr")
    for n in range(1, 5):
        name = res(body_name(n) + ".jpg")
        texture.clone("props/umbrella.jpg", name, DiffuseFile=name, AllowCompress=0)
    for name in [res(n + ".png") for n in FACE_GROUPS] + [
            res(billboard_name(n, k) + ".png") for n in range(1, 5) for k in BILLBOARD_POSES]:
        texture.clone("env/crowd_02.png", name, DiffuseFile=name, AllowCompress=0,
                      AllowResize=0)
    out["texture.wbr"] = texture

    boned = read_tpl("bonedmodel.wbr")
    for cfg, (look, _) in MODELS.items():
        boned.clone("props/umbrella.cfg", cfg, FileName=cfg,
                    ShadersList="".join(m + ";" for m in materials(look)),
                    ShadersPriorityList="0 1 2 3 4 5 ", RenderPassesFlags=0x49,
                    BoundingBoxMode=1, BoundingBoxMin=bbox[0], BoundingBoxMax=bbox[1])
    out["bonedmodel.wbr"] = boned

    # The menus pass the Lua global postingGameInLive to netman.CreateMatch
    # (its only reads). A non-LIVE profile then gets the
    # NEW_SESSION_WITHOUT_POST warning, whose Continue button restarts with
    # a local, non-posting match. Reading false creates that match at once.
    reads = 0
    for tpl in ("guigroup.wbr", "scripts.wbr"):
        w = read_tpl(tpl)
        for v, i in w.values(wbr.SCRIPT):
            kind, unk, code = v[i]
            if kind and POSTING_GLOBAL in code:
                code, n = lua51.read_global_as_false(code, POSTING_GLOBAL)
                v[i] = (kind, unk, code)
                reads += n
        out[tpl] = w
    if not reads:
        raise RuntimeError("no read of postingGameInLive found")
    print(f"  {reads} reads of postingGameInLive (CreateMatch) -> false")

    # Point the player, ghost, lobby and credits slots at the stand-in models.
    for tpl in ("fighter.wbr", "guiresource.wbr"):
        w = read_tpl(tpl)
        changed = 0
        for v, i in w.values(wbr.STRING):
            if to_model_ref(v[i]) != v[i]:
                v[i] = to_model_ref(v[i])
                changed += 1
        print(f"  {tpl}: {changed} avatar references -> BNMD")
        warn_unconverted(tpl, (v[i] for v, i in w.values(wbr.STRING)))
        out[tpl] = w
    return out


def apply_mod(layers, target, preview_dir):
    """Mod the game data seen through `layers` (highest priority first, all
    unmodified) and write every changed or new file into `target`."""

    def get(name):
        for pak in layers:
            if name in pak.index:
                return pak.get(name)
        raise KeyError(name)

    names = sorted({n for pak in layers for n in pak.index})
    put = target.put

    print("mesh + textures")
    mesh = cal3d.read_cmf(get(f"{AVATAR_DIR}/dummymodel.cmf"))
    skeleton = cal3d.read_csf(get(f"{AVATAR_DIR}/dummymodel.csf"))
    rects = normalize_face_uvs(mesh)
    mesh["submeshes"][BODY], removed = hidden_skin.fit_clothes(
        mesh["submeshes"][BODY], [b["name"] for b in skeleton["bones"]])
    print(f"  clothes bound like the body; {removed:.0%} of the body's triangles "
          "removed under them")
    put(f"{AVATAR_DIR}/dummymodel.cmf", cal3d.write_cmf(mesh))
    put(f"{AVATAR_DIR}/dummymodel.mat.txt", mat_txt(1))
    for cfg, (look, src_cfg) in MODELS.items():
        base = "data/art/" + cfg[:-len(".cfg")]
        put(base + ".cfg", get(f"{AVATAR_DIR}/{src_cfg}"))
        put(base + ".mat.txt", mat_txt(look))

    # Precache lists name resources as TAG:name, one per line.
    changed, refs = 0, []
    for name in [n for n in names if n.startswith("data/precache/")]:
        lines = get(name).decode("latin-1").split("\n")
        new = [to_model_ref(line.rstrip("\r")) + ("\r" if line.endswith("\r") else "")
               for line in lines]
        refs += [line.rstrip("\r") for line in new]
        if new != lines:
            changed += sum(a != b for a, b in zip(lines, new))
            put(name, "\n".join(new).encode("latin-1"))
    print(f"  precache: {changed} avatar entries -> BNMD")
    warn_unconverted("precache", refs)

    images = {}  # name in AVATAR_DIR -> encoded bytes, for the billboard renders

    def put_image(name, img, fmt):
        buf = io.BytesIO()
        img.save(buf, fmt, **({"quality": 95} if fmt == "JPEG" else {}))
        images[name] = buf.getvalue()
        put(f"{AVATAR_DIR}/{name}", images[name])
        with open(os.path.join(preview_dir, name), "wb") as f:
            f.write(images[name])

    body = Image.open(io.BytesIO(get(f"{AVATAR_DIR}/avatar_body_texture.jpg")))
    for n, colour in make_textures.PLAYER_SHIRTS.items():
        put_image(body_name(n) + ".jpg", make_textures.recolor_shirt(body, colour), "JPEG")
    for name, draw in (("eye", make_textures.eye), ("mouth", make_textures.mouth),
                       ("brow", make_textures.brow)):
        put_image(f"{name}.png", draw(FACE_TEX_SIZE[name], rects[name]), "PNG")

    print("billboard pictures")
    big = BILLBOARD_SIZE * 2
    for k, (anim, phase, yaw) in BILLBOARD_POSES.items():
        duration, tracks = pose.read_caf(get(f"{AVATAR_DIR}/{anim}.caf"))
        posed = pose.pose(mesh, skeleton, tracks, duration * phase)
        for n in make_textures.PLAYER_SHIRTS:
            img = render.render(posed, textures(images.__getitem__, n), W=big, H=big,
                                yaw=yaw, squash=BILLBOARD_SQUASH, bg=None, ambient=0.8)
            img = Image.fromarray(img).resize((BILLBOARD_SIZE,) * 2, Image.LANCZOS)
            put_image(billboard_name(n, k) + ".png", img, "PNG")

    put(f"{TEMPLATES}/unistrings.wbr", blank_strings(get(f"{TEMPLATES}/unistrings.wbr")))

    print("templates")
    avatar_tpl = wbr.Wbr(get(f"{TEMPLATES}/avatarmodel.wbr"))
    _, av = avatar_tpl.record("gamepad0")
    bbox = (av[avatar_tpl.field_index("BoundingBoxMin")][0],
            av[avatar_tpl.field_index("BoundingBoxMax")][0])
    templates = build_templates(lambda n: wbr.Wbr(get(f"{TEMPLATES}/{n}")), bbox)
    for name, w in templates.items():
        data = w.serialize()
        if wbr.Wbr(data).serialize() != data:
            raise RuntimeError(f"{name} does not re-parse")
        put(f"{TEMPLATES}/{name}", data)


def write_files(out, files, skip):
    os.makedirs(out, exist_ok=True)
    for path, data in files.items():
        if path not in skip:
            with open(os.path.join(out, *path.split("/")), "wb") as f:
                f.write(data)


def mod_package(src, pak_name, lower, out, preview_dir):
    """Write a package's files to `out` with its pak modded, seen on top of
    the `lower` paks. Returns the package's unmodified pak."""
    files = load_package(src)
    write_files(out, files, {pak_name})
    pak = tongaspak.Pak(files[pak_name])
    modded = tongaspak.Pak(files[pak_name])
    apply_mod([pak] + lower, modded, preview_dir)
    modded.save(os.path.join(out, pak_name))
    print(f"done: {out}")
    return pak


def main(src, out_dir, update=None):
    preview_dir = os.path.join(out_dir, "preview")
    os.makedirs(preview_dir, exist_ok=True)
    print("== base game")
    base = mod_package(src, "data.pak", [], os.path.join(out_dir, "game"), preview_dir)
    if update:
        print("== title update")
        mod_package(update, "patch.pak", [base], os.path.join(out_dir, "update"), preview_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Doritos Crash Course Xenia mod.")
    ap.add_argument("game", help="the game's XBLA package, or a .zip containing it")
    ap.add_argument("out_dir", help="output folder (game/, update/, preview/)")
    ap.add_argument("update", nargs="?", help="Title Update 2 package or .zip (for the DLC)")
    a = ap.parse_args()
    main(a.game, a.out_dir, a.update)
