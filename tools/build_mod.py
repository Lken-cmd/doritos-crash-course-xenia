"""Build the Doritos Crash Course (XBLA, 58410A71) data mod.

Xbox avatars (XAVT) are invisible in Xenia; every avatar slot becomes the
game's PC-era stand-in (data/art/_avatar) as a boned model (BNMD), one look
per player (make_textures.PLAYER_LOOKS). Adds the missing face textures and
shaders, and pre-rendered helicopter billboard pictures (the live renders
are garbage in Xenia).

usage: python build_mod.py <game package or .zip> <out_dir> [<title update>]

Writes <out_dir>/game/ and <out_dir>/preview/; with the title update also
<out_dir>/update/ (its patch.pak, which overrides data.pak, modded too;
install with install_content.py --override-dir <out_dir>/update).
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
from avatar import (AVATAR_DIR, BODY, FACE_GROUPS, FACE_TEX_SIZE, SUBMESH_SHADERS, body_name,
                    face_name, face_rect, player_cfg, res, textures)

TEMPLATES = "data/templates"

CREDITS = ["fojo", "benja", "carter", "chungi", "erich", "fco", "jean", "mike",
           "rena", "torrent"]


def credits_cfg(look):
    return res(f"credits{look}.cfg")


# XAVT:<name> -> stand-in .cfg. Resources are looked up by path, so every
# look is a real .cfg in _avatar/ with its own .mat.txt.
AVATAR_TO_MODEL = {f"gamepad{i}": player_cfg(i + 1) for i in range(4)}
AVATAR_TO_MODEL.update({f"custom{i}": player_cfg(i + 1) for i in range(4)})
AVATAR_TO_MODEL.update({"random": player_cfg(1), "default": player_cfg(1)})
AVATAR_TO_MODEL.update({f"credits/{n}": credits_cfg(i % 4 + 1) for i, n in enumerate(CREDITS)})

# cfg path -> (look, source cfg).
MODELS = {}
for _look in make_textures.PLAYER_LOOKS:
    MODELS[player_cfg(_look)] = (_look, "dummymodel.cfg")
    MODELS[credits_cfg(_look)] = (_look, "creditsmodel.cfg")

# Helicopter billboards: shader rtt/billboard<N>/pose_<K>. The game shows
# pose 1 running, 2 boosting, 3 in a wipe-out (never 4) and mirrors it to
# the running direction. Frames as in gameconfig PoseRun/PoseBoost/PoseWipeOut:
# (animation, seconds), side-on. 256x256 stretched over a 4:3 quad: squash.
BILLBOARD_POSES = {1: ("jog_01", 0.336), 2: ("run_boost", 0.35), 3: ("run_boost_fall", 0.746),
                   4: ("jog_01", 0.336)}
BILLBOARD_YAW = 90
BILLBOARD_SIZE = 256
BILLBOARD_SQUASH = 0.75

# Blanked in unistrings.wbr (u32 length + UTF-16LE); always shown offline.
BLANK_STRINGS = ["A gamer profile connected to Xbox LIVE is required to view the leaderboard."]
POSTING_GLOBAL = b"postingGameInLive"
LOCAL_LOBBY = "menus/local_multiplayer/lobby"


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
        rects[name] = face_rect(name, (u0, v0), (u1, v1))
    return rects


def billboard_name(n, k):
    return f"billboard_p{n}_{k}"


def materials(look):
    """Shader names per submesh, in .mat.txt order (see avatar.textures)."""
    return [res(face_name(s, look)) for s in SUBMESH_SHADERS] + [res(body_name(look))]


def mat_txt(look):
    return ("\n".join(materials(look)) + "\nendmats\n").encode()


def blank_strings(data):
    for s in BLANK_STRINGS:
        old = struct.pack("<I", len(s)) + s.encode("utf-16-le")
        if data.count(old) != 1:
            raise ValueError(f"string not found exactly once: {s!r}")
        data = data.replace(old, struct.pack("<I", 1) + " ".encode("utf-16-le"))
    return data


def lobby_by_join_order(guigroup):
    """Local lobby frames by join order: the frame loop asks netman.IsSlotUsed(frame + "4")
    (exe patch: >= 4 means join index) instead of IsSlotUsed(frame) (controller). The exe
    patch also makes gui.GameGamepadName take the join index."""
    _, vals = guigroup.record(LOCAL_LOBBY)
    scripts = vals[guigroup.field_index("OnActivateCommand")]
    kind, unk, code = scripts[0]
    func = next(f for f, (_, _, consts) in enumerate(lua51.functions(code))
                if b"GameGamepadName" in consts)
    code, k4 = lua51.add_string_constant(code, func, "4")
    consts = lua51.functions(code)[func][2]
    call = [lua51.abc(lua51.OP["GETTABLE"], 5, 5, lua51.RK + consts.index(b"IsSlotUsed")),
            lua51.abc(lua51.OP["MOVE"], 6, 4, 0), lua51.abc(lua51.OP["CALL"], 5, 2, 2)]
    ins = lua51.instructions(code, func)
    at = [p for p in range(len(ins) - 2) if ins[p:p + 3] == call]
    if len(at) != 2:  # the start-button count, then the frame loop
        raise RuntimeError(f"lobby script: expected 2 IsSlotUsed calls, found {len(at)}")
    code = lua51.set_code(code, func, at[1] + 1,
                          [lua51.abc(lua51.OP["ADD"], 6, 4, lua51.RK + k4)])
    scripts[0] = (kind, unk, code)


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
    for name in (face_name(g, n) for n in make_textures.PLAYER_LOOKS for g in FACE_GROUPS):
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
    for name in [res(face_name(g, n) + ".png")
                 for n in make_textures.PLAYER_LOOKS for g in FACE_GROUPS] + [
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

    # postingGameInLive is only read for netman.CreateMatch; true gives a
    # non-LIVE profile the NEW_SESSION_WITHOUT_POST warning. Read it as false.
    reads = 0
    for tpl in ("guigroup.wbr", "scripts.wbr"):
        w = read_tpl(tpl)
        for v, i in w.values("script"):
            kind, unk, code = v[i]
            if kind and POSTING_GLOBAL in code:
                code, n = lua51.read_global_as_false(code, POSTING_GLOBAL)
                v[i] = (kind, unk, code)
                reads += n
        out[tpl] = w
    if not reads:
        raise RuntimeError("no read of postingGameInLive found")
    print(f"  {reads} reads of postingGameInLive (CreateMatch) -> false")
    lobby_by_join_order(out["guigroup.wbr"])

    # Player, ghost, lobby and credits slots.
    for tpl in ("fighter.wbr", "guiresource.wbr"):
        w = read_tpl(tpl)
        changed = 0
        for v, i in w.values("str"):
            if to_model_ref(v[i]) != v[i]:
                v[i] = to_model_ref(v[i])
                changed += 1
        print(f"  {tpl}: {changed} avatar references -> BNMD")
        warn_unconverted(tpl, (v[i] for v, i in w.values("str")))
        out[tpl] = w
    return out


def apply_mod(layers, target, preview_dir):
    """Mod the data seen through `layers` (unmodified paks, highest priority
    first); write changed and new files into `target`."""

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

    # Precache lists: TAG:name per line.
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

    images = {}  # name in AVATAR_DIR -> encoded bytes (for the billboard renders)

    def put_image(name, img, fmt):
        buf = io.BytesIO()
        # No chroma subsampling: it blurs the shirt stripes.
        img.save(buf, fmt, **({"quality": 95, "subsampling": 0} if fmt == "JPEG" else {}))
        images[name] = buf.getvalue()
        put(f"{AVATAR_DIR}/{name}", images[name])
        with open(os.path.join(preview_dir, name), "wb") as f:
            f.write(images[name])

    size = Image.open(io.BytesIO(get(f"{AVATAR_DIR}/avatar_body_texture.jpg"))).size
    for n, look in make_textures.PLAYER_LOOKS.items():
        put_image(body_name(n) + ".jpg", make_textures.body(size, look), "JPEG")
        for name, draw in make_textures.FACE_DRAW.items():
            put_image(face_name(name, n) + ".png",
                      draw(FACE_TEX_SIZE[name], rects[name], look.face), "PNG")

    print("billboard pictures")
    big = BILLBOARD_SIZE * 2
    posed = {}
    for k, (anim, time) in BILLBOARD_POSES.items():
        _, tracks = pose.read_caf(get(f"{AVATAR_DIR}/{anim}.caf"))
        posed[k] = pose.pose(mesh, skeleton, tracks, time)
    # One view for all poses (the game's camera is fixed).
    frame = render.frame_of({"submeshes": [sm for m in posed.values() for sm in m["submeshes"]]})
    for k in BILLBOARD_POSES:
        for n in make_textures.PLAYER_LOOKS:
            img = render.render(posed[k], textures(images.__getitem__, n),
                                W=big, H=big, yaw=BILLBOARD_YAW, squash=BILLBOARD_SQUASH,
                                bg=None, ambient=0.8, frame=frame)
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
        put(f"{TEMPLATES}/{name}", w.serialize_checked(name))


def write_files(out, files, skip):
    os.makedirs(out, exist_ok=True)
    for path, data in files.items():
        if path not in skip:
            with open(os.path.join(out, *path.split("/")), "wb") as f:
                f.write(data)


def mod_package(src, pak_name, lower, out, preview_dir):
    """Write a package's files to `out` with its pak modded on top of the
    `lower` paks. Returns the unmodified pak."""
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
