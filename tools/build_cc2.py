"""Build the Doritos Crash Course 2 data.pak for Xenia (exe changes: patches/5841124F*.toml).

- splash: no wait for the LiveGamer (server) profile download
- menus: no Xbox LIVE banner, no coins; courses cost stars only
- results: Recommended Item shows a random shop item description
- local multiplayer: lobby panel k shows player k's look (players numbered by join order)
- Xbox avatars (XAVT, which crash in Xenia) -> copies of the game's stand-in model:
  _avatar/player<N>.cfg per player number, _avatar/ai_<name>.cfg per AI racer
- stand-in: face and body textures, clothes fitted (hidden_skin)
"""
import argparse
import io
import os
import re
import hashlib
import struct
from typing import NamedTuple, Optional

import numpy as np

import cal3d
import cmfh
import hidden_skin
import lua51
import make_textures
import tongaspak
import wbr
from avatar import (ART, AVATAR_DIR, BODY, FACE_GROUPS, FACE_TEX_SIZE, body_name, face_rect,
                    player_cfg, res)

TEMPLATES = "data/templates"
STAND_IN_CFG = res("dummymodel.cfg")
STAND_IN = "BNMD:" + STAND_IN_CFG
SPLASH = "common/ui/men/splash/main"
LIVE_TICKERS = ["common/ui/men/main/main", "common/ui/men/pause/main"]
# Balances (top right) and "Get Coins" prompts.
STAR_COIN_COUNTER = "common/ui/men/star_coin_counter"
COIN_CONTROLS = ["get_coins_supertop", "get_coins_bottom", "get_coins_top", "coin",
                 "coin_num"]
# Star and rewind balances move right into the coin's places.
BALANCE_MOVES = [("star", "coin"), ("star_num", "coin_num"), ("rewind", "star"),
                 ("rewind_num", "star_num")]
# Coin prices; hidden, as -1 per course shows e.g. "-3" for a theme.
COIN_PRICES = ["common/ui/men/coin_counter", "common/ui/men/shop/coin_counter_orange"]
# Online the shop picked the item; offline the panel shows lorem ipsum.
RECOMMENDED = "common/ui/men/tally/recommended_item"
# Adds the players to the session in join order; the race numbers them in session order.
LOCAL_LOBBY = "common/ui/men/mp/local/lobby"
ITEM_DESCRIPTION = "common/ui/men/tally/item_description"
SHOP_DESC = "common/ui/men/shop/desc/"
SHOP_DESC_SKIP = {SHOP_DESC + "moneybags"}  # developer placeholder
# The stand-in's own face shaders; the copies' variants are numbered in the same folders.
FACE_SHADER_DIRS = {"mouth": res("mouth"), "eye": res("eye"), "brow": res("eyebrows")}
FACE_SHADERS = {g: f"{d}/0" for g, d in FACE_SHADER_DIRS.items()}
BODY_SHADER = res("body")
BODY_TEX_SIZE = (256, 256)
# Look per player number (P1-P4 = race slot = lobby panel, by join order), shirts in the
# HUD's P1-P4 colours. Race: BNMD:_avatar/player%d.cfg by slot (exe
# patch); lobby panel k: gui/lobby<k>; menus: P1's look.
SLOT_LOOKS = [make_textures.player_look((60, 185, 40), "green"),
              make_textures.player_look((215, 40, 25), "red"),
              make_textures.player_look((30, 150, 215), "blue"),
              make_textures.player_look((160, 50, 190), "purple")]
MENU_AVATAR = re.compile(r"XAVT:gui/gamepad\d$")  # the menu owner's avatar (gui/gamepad<pad>)
CONTROLLER_AVATAR = re.compile(r"XAVT:(?:gamepad|clips/custom)(\d)$")
# AI racers: gameclips data/clips/<theme>/<track>/<time>_<name>.clip, recorded with avatar
# ai/<name> (AI_DIR/<name>.amd); the exe patch loads BNMD:_avatar/ai_<name>.cfg.
AI_DIR = f"{AVATAR_DIR}/ai"
AI_CLIP = re.compile(r"data/clips/.*/\d+_\d+_\d+_(\w+)\.clip$")
AI_TEX_SIZE = (128, 128)
AI_SHIRTS = [(200, 60, 50), (60, 120, 190), (230, 200, 60), (90, 160, 80), (150, 90, 170),
             (235, 235, 230), (70, 70, 75), (230, 130, 40), (40, 170, 170), (230, 120, 160),
             (120, 70, 40), (30, 60, 120)]
AI_HAIR = [make_textures.BROWN, make_textures.BLACK, make_textures.BLOND, make_textures.GINGER]
AI_TROUSERS = [make_textures.JEANS, make_textures.BLACK, make_textures.KHAKI, make_textures.GREY,
               (62, 78, 46), (92, 58, 34)]
AI_SHOES = [make_textures.WHITE, make_textures.BLACK, make_textures.BROWN, (168, 32, 30)]
# Builds besides the stand-in's own: metres the body moves outwards (with_build); an AI
# racer's follows its avatar's weight.
BUILDS = {"slim": -0.010, "heavy": 0.018}
# Lua binding the Xenia patch turns into "create the shop" (only an unused menu needs it).
SHOP_CREATOR = "ProfileGetIsSplitPathUnlock"
OP = lua51.OP


class StandInCopy(NamedTuple):
    """A stand-in copy. build: BUILDS key or None (the stand-in's own mesh)."""
    body: str
    look: make_textures.Look
    size: tuple
    build: Optional[str] = None


class XAvatar(NamedTuple):
    """From an AI racer's .amd (XAVATAR_METADATA): ARGB colours at 0xFC, weight
    (float, -1..1) at +8."""
    skin: tuple
    hair: tuple
    lips: tuple
    eyes: tuple
    brows: tuple
    weight: float


def ai_cfg(name):
    return res(f"ai_{name}.cfg")


def ai_names(pak):
    """AI racer names from the clips and AI_DIR."""
    clips = {m[1] for m in map(AI_CLIP.match, pak.index) if m}
    amds = {n[len(AI_DIR) + 1:-len(".amd")] for n in pak.index
            if n.startswith(AI_DIR + "/") and n.endswith(".amd")}
    return sorted(clips | amds)


def xavatar(pak, name):
    """None for the clip avatars without an .amd."""
    amd = f"{AI_DIR}/{name}.amd"
    if amd not in pak.index:
        return None
    data = pak.get(amd)
    rgb = [((c >> 16) & 255, (c >> 8) & 255, c & 255)
           for c in struct.unpack_from(">5I", data, 0xFC)]
    weight, = struct.unpack_from(">f", data, 8)
    return XAvatar(*rgb, weight)


def nearest(palette, rgb):
    return min(palette.values(), key=lambda c: sum((a - b) ** 2 for a, b in zip(c, rgb)))


def picker(name):
    """pick(options): stable per `name` (next byte of its hash per call)."""
    digest = iter(hashlib.sha1(name.encode()).digest())

    def pick(options):
        options = list(options)
        return options[next(digest) % len(options)]
    return pick


def ai_look(name, avatar):
    """Colours from the avatar (face colours snapped to the palettes, so racers share face
    textures); everything else picked by name."""
    pick = picker(name)
    face = make_textures.Face(iris=pick(make_textures.IRIS_COLOURS.values()),
                              eye_size=pick([0.85, 1.0, 1.15]), eye_tilt=pick([-0.02, 0.0, 0.03]),
                              brow_shape=pick(make_textures.BROW_SHAPES),
                              brow_colour=pick(make_textures.BROW_COLOURS.values()),
                              mouth_shape=pick(make_textures.MOUTH_SHAPES),
                              lip_colour=pick(make_textures.LIP_COLOURS.values()))
    look = make_textures.Look(pick(AI_SHIRTS), trousers=pick(AI_TROUSERS), shoes=pick(AI_SHOES),
                              hair=pick(AI_HAIR), face=face)
    if avatar is None:
        return look
    face = face._replace(iris=nearest(make_textures.IRIS_COLOURS, avatar.eyes),
                         brow_colour=nearest(make_textures.BROW_COLOURS, avatar.brows),
                         lip_colour=nearest(make_textures.LIP_COLOURS, avatar.lips))
    return look._replace(skin=avatar.skin, hair=avatar.hair, face=face)


def ai_build(avatar):
    """Slim or heavy after the avatar's weight."""
    if avatar is None:
        return None
    return "slim" if avatar.weight <= -0.5 else "heavy" if avatar.weight >= 0.5 else None


def stand_in_copies(pak):
    """{model resource name: StandInCopy} of the players and AI racers."""
    copies = {player_cfg(n): StandInCopy(res(body_name(n)), look, BODY_TEX_SIZE)
              for n, look in enumerate(SLOT_LOOKS)}
    for name in ai_names(pak):
        avatar = xavatar(pak, name)
        copies[ai_cfg(name)] = StandInCopy(f"{BODY_SHADER}_ai_{name}", ai_look(name, avatar),
                                           AI_TEX_SIZE, ai_build(avatar))
    return copies


def body_submeshes(mesh):
    """Indices of the stand-in's body submeshes (one per bone palette)."""
    return [i for i, s in enumerate(mesh.submeshes) if s["material"] == BODY]


def mesh_name(build):
    """A build's mesh as a .cfg names it (the game loads the baked .cmfh)."""
    return "DummyModel.CMF" if build is None else f"DummyModel_{build}.CMF"


def with_build(mesh, d):
    """Copy of the stand-in's mesh, slimmer (d < 0) or heavier: the body below the neck,
    without hands and shoes, moves d metres out from the middle line of torso, legs and
    arms (bind pose: arms along x, z up, feet at 0). Depends on position only, so clothes,
    skin under them and submesh seams move together."""
    out = cmfh.Mesh(mesh.serialize())
    rows = out.rows(body_submeshes(out))
    pos = out.verts[rows][:, cmfh.POS]
    x, z = pos[:, 0], pos[:, 2]

    def outwards(keys, axes):
        """Unit vectors from the middle of each vertex's slice (same key), within `axes`."""
        _, slice_of = np.unique(keys, axis=0, return_inverse=True)
        slice_of = slice_of.reshape(-1)
        middle = np.zeros((slice_of.max() + 1, 3))
        np.add.at(middle, slice_of, pos)
        middle /= np.bincount(slice_of)[:, None]
        r = (pos - middle[slice_of]) * [a in axes for a in range(3)]
        return r / (np.linalg.norm(r, axis=1, keepdims=True) + 1e-9)

    side, height, reach = np.sign(x), np.round(z / 0.02), np.round(np.abs(x) / 0.02)
    leg = np.clip((0.76 - z) / 0.08, 0, 1)[:, None]
    arm = (np.clip((np.abs(x) - 0.17) / 0.08, 0, 1) * (z > 0.9))[:, None]
    way = outwards(np.c_[height], (0, 1)) * (1 - leg) + outwards(np.c_[side, height], (0, 1)) * leg
    way = way * (1 - arm) + outwards(np.c_[side, reach], (1, 2)) * arm
    way /= np.linalg.norm(way, axis=1, keepdims=True) + 1e-9
    fade = (np.clip((1.12 - z) / 0.06, 0, 1) * np.clip((0.56 - np.abs(x)) / 0.06, 0, 1)
            * np.clip((z - 0.06) / 0.06, 0, 1))
    out.verts[rows, cmfh.POS] = pos + way * (d * fade)[:, None]
    return out


def texture_of(shader):
    return shader + ".png"


def tpl(pak, name):
    return wbr.Wbr(pak.get(f"{TEMPLATES}/{name}"), wbr.TYPES_CC2)


def put_tpl(pak, name, w):
    pak.put(f"{TEMPLATES}/{name}", w.serialize_checked(name))


def skip_livegamer_wait(guigroup):
    """In the splash start handler, replace
        if not WaitForProfileLgInfo(gui.GetInputDevice(), me) then return end
    (waits for LiveGamer, creates the shop with the course lists, calls me:Done) with
        SHOP_CREATOR(gui.GetInputDevice()); me:Done(gui.GetInputDevice()); return"""
    _, vals = guigroup.record(SPLASH)
    for (_, t), v in zip(guigroup.fields, vals):
        if v is None or guigroup.types[t][0] != "script":
            continue
        for i, (kind, unk, code) in enumerate(v):
            if kind != 2 or b"WaitForProfileLgInfo" not in code:
                continue
            code, k_done = lua51.add_string_constant(code, 0, "Done")
            code, k_shop = lua51.add_string_constant(code, 0, SHOP_CREATOR)
            _, n, consts = lua51.functions(code)[0]
            ins = lua51.instructions(code, 0)
            k = consts.index
            want = [lua51.abx(OP["GETGLOBAL"], 0, k(b"WaitForProfileLgInfo")),
                    lua51.abx(OP["GETGLOBAL"], 1, k(b"gui")),
                    lua51.abc(OP["GETTABLE"], 1, 1, lua51.RK + k(b"GetInputDevice")),
                    lua51.abc(OP["CALL"], 1, 1, 2),
                    lua51.abx(OP["GETGLOBAL"], 2, k(b"me")),
                    lua51.abc(OP["CALL"], 0, 3, 2),
                    lua51.abc(OP["TEST"], 0, 0, 1),
                    lua51.abx(OP["JMP"], 0, 1 + lua51.SBX),
                    lua51.abc(OP["RETURN"], 0, 1, 0)]
            pc = next((p for p in range(n - len(want)) if ins[p:p + len(want)] == want), None)
            if pc is None:
                raise RuntimeError("the splash script's WaitForProfileLgInfo call has an "
                                   "unexpected shape (an already modded data.pak?)")
            # 3 instructions longer; the overwritten ones are only reached by falling through.
            new_end = pc + 12
            for p, w in enumerate(ins):
                to = lua51.jump_target(p, w)
                if to is not None and not pc <= p < pc + len(want) \
                        and pc + len(want) <= to < new_end:
                    raise RuntimeError(f"pc {p} jumps into the replaced code")
            code = lua51.set_code(code, 0, pc, [
                # The binding needs exactly 1 argument.
                lua51.abx(OP["GETGLOBAL"], 0, k_shop),
                lua51.abx(OP["GETGLOBAL"], 1, k(b"gui")),
                lua51.abc(OP["GETTABLE"], 1, 1, lua51.RK + k(b"GetInputDevice")),
                lua51.abc(OP["CALL"], 1, 1, 2),
                lua51.abc(OP["CALL"], 0, 2, 1),
                lua51.abx(OP["GETGLOBAL"], 0, k(b"me")),
                lua51.abc(OP["SELF"], 0, 0, lua51.RK + k_done),
                lua51.abx(OP["GETGLOBAL"], 2, k(b"gui")),
                lua51.abc(OP["GETTABLE"], 2, 2, lua51.RK + k(b"GetInputDevice")),
                lua51.abc(OP["CALL"], 2, 1, 2),
                lua51.abc(OP["CALL"], 0, 3, 1),
                lua51.abc(OP["RETURN"], 0, 1, 0)])
            v[i] = (kind, unk, code)
            return
    raise RuntimeError("WaitForProfileLgInfo call not found")


def hide_live_tickers(guigroup):
    """Hide the Avatar FameStar banner (offline it only says "connect to Xbox LIVE")."""
    for group in LIVE_TICKERS:
        _, vals = guigroup.record(group)
        names = vals[guigroup.field_index("ControlName")]
        vals[guigroup.field_index("ControlVisible")][names.index("ticker")] = 0


def hide_coins(guigroup):
    """Hide coins (real money): opacity 0, as scripts toggle Visible. Star and rewind
    balances move into the free slots."""
    def hide(group, controls):
        _, vals = guigroup.record(group)
        names = vals[guigroup.field_index("ControlName")]
        for name in controls:
            vals[guigroup.field_index("ControlOpacity")][names.index(name)] = 0.0
            vals[guigroup.field_index("ControlVisible")][names.index(name)] = 0
        return names, vals[guigroup.field_index("ControlPos")]

    for group in COIN_PRICES:
        hide(group, ["coin", "coin_num"])
    names, pos = hide(STAR_COIN_COUNTER, COIN_CONTROLS)
    slot = {name: pos[names.index(name)] for move in BALANCE_MOVES for name in move}
    for name, to in BALANCE_MOVES:
        pos[names.index(name)] = slot[to]


def lobby_panel_looks(guigroup):
    """Lobby panel avatars by panel instead of pad: on activation join<k> gets prop lookIdx = k;
    SetGamepadInfo shows GACT:lobby<slot.lookIdx> instead of GACT:gamepad<pad>. Panels are
    handed out in join order, like the session slots."""
    _, vals = guigroup.record(LOCAL_LOBBY)
    scripts = vals[guigroup.field_index("OnActivateCommand")]
    kind, unk, code = scripts[0]
    func = next(f for f, (_, _, consts) in enumerate(lua51.functions(code))
                if b"RegisterLobbyPreviewer" in consts and b"GACT:gamepad" in consts)
    code, k_name = lua51.add_string_constant(code, func, "GACT:lobby")
    code, k_look = lua51.add_string_constant(code, func, "lookIdx")
    consts = lua51.functions(code)[func][2]
    ins = lua51.instructions(code, func)
    old = [lua51.abx(OP["LOADK"], 5, consts.index(b"GACT:gamepad")), lua51.abc(OP["MOVE"], 6, 2, 0)]
    pc = next((p for p in range(len(ins) - 1) if ins[p:p + 2] == old), None)
    if pc is None:
        raise RuntimeError("SetGamepadInfo has an unexpected shape")
    code = lua51.set_code(code, func, pc, [lua51.abx(OP["LOADK"], 5, k_name),
                                            lua51.abc(OP["GETTABLE"], 6, 1, lua51.RK + k_look)])
    k = {}
    for name in ["me", "AddProp", "lookIdx"] + [f"join{i}" for i in range(4)]:
        code, k[name] = lua51.add_string_constant(code, 0, name)
    consts = lua51.functions(code)[0][2]
    numbers = [next(j for j, c in enumerate(consts) if type(c) is float and c == i) for i in range(4)]
    if max(k[f"join{i}"] for i in range(4)) >= lua51.RK or k["AddProp"] >= lua51.RK:
        raise RuntimeError("lobby constants out of RK range")
    # GUI controls drop plain fields: me.join<i>.AddProp("lookIdx", i)
    code = lua51.prepend_code(code, 0, [w for i in range(4) for w in (
        lua51.abx(OP["GETGLOBAL"], 0, k["me"]),
        lua51.abc(OP["GETTABLE"], 0, 0, lua51.RK + k[f"join{i}"]),
        lua51.abc(OP["GETTABLE"], 0, 0, lua51.RK + k["AddProp"]),
        lua51.abx(OP["LOADK"], 1, k["lookIdx"]),
        lua51.abx(OP["LOADK"], 2, numbers[i]),
        lua51.abc(OP["CALL"], 0, 3, 1))], 3)
    scripts[0] = (kind, unk, code)


def lobby_actors(actors, guiactors):
    """GACT:lobby<k> (guiactor) -> actor gui/lobby<k>: gui/gamepad's platform and holo with
    player k's model."""
    for n in range(len(SLOT_LOOKS)):
        _, vals = actors.record(f"gui/gamepad{n}")
        resources = [("BNMD:" + player_cfg(n)) if r.startswith("BNMD:_avatar/") else r
                     for r in vals[actors.field_index("Resources")]]
        actors.clone(f"gui/gamepad{n}", f"gui/lobby{n}", Resources=resources)
        guiactors.clone(f"gamepad{n}", f"lobby{n}", ActorResources=[f"gui/lobby{n}"])


def stars_only(levelconfig):
    """Coin prices -1: hides them and the coin purchase option (FillIn checks cost >= 0)."""
    for _, vals in levelconfig.records:
        for field in ("CoinsCost", "SplitPathCoinsCost"):
            vals[levelconfig.field_index(field)] = [-1]
    return len(levelconfig.records)


def random_recommendation(guigroup, unistrings):
    """Prepend me.desc.Text = GetUnistring(descs[math.random(#descs)]) to the panel's
    activation script (descs: shop item descriptions; the placeholder text becomes the
    first). Returns len(descs)."""
    descs = [k for k, _ in unistrings.records
             if k.startswith(SHOP_DESC) and k not in SHOP_DESC_SKIP]
    _, src = unistrings.record(descs[0])
    unistrings.edit(ITEM_DESCRIPTION, **{f: list(src[unistrings.field_index(f)])
                                         for f in ("LocalizeSubLang", "Localize", "LocalizedText")})
    _, vals = guigroup.record(RECOMMENDED)
    scripts = vals[guigroup.field_index("OnActivateCommand")]
    kind, unk, code = scripts[0]
    k = {}
    for s in descs + ["math", "random", "GetUnistring", "me", "desc", "Text"]:
        code, k[s] = lua51.add_string_constant(code, 0, s)
    n = len(descs)
    code = lua51.prepend_code(code, 0, [
        lua51.abc(OP["NEWTABLE"], 0, 0, 0),
        *[lua51.abx(OP["LOADK"], 1 + i, k[s]) for i, s in enumerate(descs)],
        lua51.abc(OP["SETLIST"], 0, n, 1),                            # R0 = descs
        lua51.abx(OP["GETGLOBAL"], 1, k["math"]),
        lua51.abc(OP["GETTABLE"], 1, 1, lua51.RK + k["random"]),
        lua51.abc(OP["LEN"], 2, 0, 0),
        lua51.abc(OP["CALL"], 1, 2, 2),                               # R1 = math.random(#R0)
        lua51.abc(OP["GETTABLE"], 1, 0, 1),                           # R1 = R0[R1]
        lua51.abx(OP["GETGLOBAL"], 2, k["GetUnistring"]),
        lua51.abc(OP["MOVE"], 3, 1, 0),
        lua51.abc(OP["CALL"], 2, 2, 2),                               # R2 = GetUnistring(R1)
        lua51.abx(OP["GETGLOBAL"], 3, k["me"]),
        lua51.abc(OP["GETTABLE"], 3, 3, lua51.RK + k["desc"]),
        lua51.abc(OP["SETTABLE"], 3, lua51.RK + k["Text"], 2),        # me.desc.Text = R2
    ], 1 + n)
    scripts[0] = (kind, unk, code)
    return n


def to_model_ref(ref):
    """XAVT:<avatar> -> a player model (menus: P1's), or the stand-in."""
    if MENU_AVATAR.match(ref):
        return "BNMD:" + player_cfg(0)
    m = CONTROLLER_AVATAR.match(ref)
    return "BNMD:" + player_cfg(int(m[1])) if m else STAND_IN


def stand_in_avatars(w):
    changed = 0
    for v, i in w.values("str"):
        if v[i].startswith("XAVT:"):
            v[i] = to_model_ref(v[i])
            changed += 1
    return changed


def precache_stand_in(w, copies):
    """Precache lists ("\\r\\n"-separated TAG:name): XAVT -> stand-in, plus every copy, so
    they load with the level (loading on demand in the main thread can deadlock)."""
    players = {"BNMD:" + name for name in copies}
    changed = 0
    for v, i in w.values("str"):
        s = v[i]
        if "XAVT:" not in s or "\r\n" not in s:
            continue
        lines = [x for x in s.split("\r\n") if x]
        kept = sorted({to_model_ref(x) if x.startswith("XAVT:") else x for x in lines}
                      | {STAND_IN} | players)
        v[i] = "\r\n" + "\r\n".join(kept) + "\r\n"
        changed += 1
    return changed


def face_uvs(mesh):
    """Stretch each face group's UVs over its texture. Returns {group: rect}: the original
    0..1 UV square in FACE_TEX_SIZE pixels."""
    rects = {}
    for name, ids in FACE_GROUPS.items():
        uv = np.concatenate([mesh.submesh(i)[0][:, cmfh.UV] for i in ids])
        lo, hi = uv.min(0), uv.max(0)
        for i in ids:
            mesh.set_uvs(i, (mesh.submesh(i)[0][:, cmfh.UV] - lo) / (hi - lo))
        rects[name] = face_rect(name, lo, hi)
    return rects


# The Face fields each face group's texture shows.
FACE_PARTS = {"eye": ("iris", "eye_size", "eye_tilt"),
              "brow": ("brow_shape", "brow_colour"),
              "mouth": ("mouth_shape", "lip_colour")}


class FacePart(NamedTuple):
    shader: str
    texture: str
    face: make_textures.Face  # a face with this part
    scale: float  # of the texture, relative to FACE_TEX_SIZE


def face_key(group, face):
    return group, tuple(getattr(face, f) for f in FACE_PARTS[group])


def face_parts(copies):
    """{face_key: FacePart} for every face part in use. The stand-in's keep their shaders;
    the others are shared between copies, at half size (dozens load per race)."""
    default = make_textures.Face()
    parts = {face_key(g, default): FacePart(FACE_SHADERS[g], res(f"{g}.png"), default, 1)
             for g in FACE_GROUPS}
    for c in copies.values():
        for g in FACE_GROUPS:
            key = face_key(g, c.look.face)
            if key not in parts:
                k = sum(1 for other, _ in parts if other == g)
                parts[key] = FacePart(f"{FACE_SHADER_DIRS[g]}/{k}", res(f"{g}_{k}.png"),
                                      c.look.face, 0.5)
    return parts


def face_image(group, rects, part):
    w, h = FACE_TEX_SIZE[group]
    s = part.scale
    return make_textures.FACE_DRAW[group]((int(w * s), int(h * s)),
                                          tuple(c * s for c in rects[group]), part.face)


def fit_clothes(mesh, skeleton):
    """hidden_skin.fit on the body submeshes, merged into one (CC1's mesh, mirrored)."""
    body = body_submeshes(mesh)
    merged, welded = mesh.merged(body)
    fitted, drop, share = hidden_skin.fit(merged, [b["name"] for b in skeleton["bones"]])
    lost = mesh.set_merged(body, merged, fitted, welded, drop)
    print(f"  clothes bound like the body; {share:.0%} of the body's triangles removed "
          f"under them ({lost} vertices lost a minor bone missing from their palette)")


def face_templates(shader, texture, parts):
    for p in parts.values():
        shader.clone(BODY_SHADER, p.shader, MultilayerDiffuse=p.texture, Culling=0, AlphaTest=128)
        texture.clone("gs/randnormal.png", p.texture, DiffuseFile=p.texture, AllowCompress=0,
                      AllowResize=0, Mipmaps=1)


def body_templates(shader, texture, copies):
    """Body shader: our texture instead of the flat blue placeholder; one shader per copy."""
    shader.edit(BODY_SHADER, MultilayerDiffuse=texture_of(BODY_SHADER))
    players = [c.body for c in copies.values()]
    for name in players:
        shader.clone(BODY_SHADER, name, MultilayerDiffuse=texture_of(name))
    for name in [BODY_SHADER] + players:
        texture.clone("common/ch/shark/shark_d.png", texture_of(name),
                      DiffuseFile=texture_of(name), AllowResize=0)


def stand_in_models(pak, boned, copies, parts):
    """Per copy: .cfg (own mesh), .mat.txt (own shaders), bonedmodel record. The copies sit
    next to dummymodel.cfg and share its skeleton and animations."""
    cfg = pak.get(f"{AVATAR_DIR}/dummymodel.cfg").decode("latin-1")
    mats = pak.get(f"{AVATAR_DIR}/dummymodel.mat.txt").decode("latin-1").split("\n")
    _, vals = boned.record(STAND_IN_CFG)
    shaders = vals[boned.field_index("ShadersList")][0].split(";")
    if cfg.count(f"mesh={mesh_name(None)}") != 1:
        raise RuntimeError("dummymodel.cfg: mesh line not found")
    for name, c in copies.items():
        own = {BODY_SHADER: c.body}
        own.update({s: parts[face_key(g, c.look.face)].shader for g, s in FACE_SHADERS.items()})
        base = f"{ART}/{name[:-len('.cfg')]}"
        pak.put(base + ".cfg", cfg.replace(f"mesh={mesh_name(None)}",
                                           f"mesh={mesh_name(c.build)}").encode("latin-1"))
        mat_txt = "\n".join(own.get(m.rstrip("\r"), m.rstrip("\r")) + m[len(m.rstrip("\r")):]
                            for m in mats)
        pak.put(base + ".mat.txt", mat_txt.encode("latin-1"))
        boned.clone(STAND_IN_CFG, name, FileName=name,
                    ShadersList=";".join(own.get(s, s) for s in shaders))


def apply_mod(pak, preview_dir=None):
    guigroup, unistrings = tpl(pak, "guigroup.wbr"), tpl(pak, "unistrings.wbr")
    skip_livegamer_wait(guigroup)
    hide_live_tickers(guigroup)
    hide_coins(guigroup)
    lobby_panel_looks(guigroup)
    n = random_recommendation(guigroup, unistrings)
    put_tpl(pak, "guigroup.wbr", guigroup)
    put_tpl(pak, "unistrings.wbr", unistrings)
    print("  splash: no LiveGamer wait; menus: no Xbox LIVE banner, no coin balance; "
          "local multiplayer: lobby panels by join order; "
          f"results: Recommended Item shows one of {n} shop item descriptions")

    levelconfig = tpl(pak, "levelconfig.wbr")
    print(f"  levelconfig: {stars_only(levelconfig)} courses priced in stars only")
    put_tpl(pak, "levelconfig.wbr", levelconfig)

    actors = tpl(pak, "actorresources.wbr")
    print(f"  actorresources: {stand_in_avatars(actors)} Xbox avatars -> stand-in models")
    guiactors = tpl(pak, "guiactor.wbr")
    lobby_actors(actors, guiactors)
    put_tpl(pak, "actorresources.wbr", actors)
    put_tpl(pak, "guiactor.wbr", guiactors)

    copies = stand_in_copies(pak)
    precache = tpl(pak, "precache.wbr")
    print(f"  precache: {precache_stand_in(precache, copies)} lists precache the stand-in models")
    put_tpl(pak, "precache.wbr", precache)

    mesh = cmfh.Mesh(pak.get(f"{AVATAR_DIR}/dummymodel.cmfh"))
    skeleton = cal3d.read_csf(pak.get(f"{AVATAR_DIR}/p_test.csf"))
    fit_clothes(mesh, skeleton)
    rects = face_uvs(mesh)
    parts = face_parts(copies)
    images = {p.texture: face_image(g, rects, p) for (g, _), p in parts.items()}
    images[texture_of(BODY_SHADER)] = make_textures.body(BODY_TEX_SIZE)
    for c in copies.values():
        images[texture_of(c.body)] = make_textures.body(c.size, c.look)
    for name, img in images.items():
        buf = io.BytesIO()
        img.save(buf, "PNG")
        pak.put(f"{ART}/{name}", buf.getvalue())
        if preview_dir:
            img.save(os.path.join(preview_dir, os.path.basename(name)))
    pak.put(f"{AVATAR_DIR}/dummymodel.cmfh", mesh.serialize())
    for build, d in BUILDS.items():
        pak.put(f"{AVATAR_DIR}/{mesh_name(build).lower()[:-len('.cmf')]}.cmfh",
                with_build(mesh, d).serialize())
    shader, texture = tpl(pak, "shader.wbr"), tpl(pak, "texture.wbr")
    face_templates(shader, texture, parts)
    body_templates(shader, texture, copies)
    put_tpl(pak, "shader.wbr", shader)
    put_tpl(pak, "texture.wbr", texture)
    boned = tpl(pak, "bonedmodel.wbr")
    stand_in_models(pak, boned, copies, parts)
    put_tpl(pak, "bonedmodel.wbr", boned)
    builds = sum(c.build is not None for c in copies.values())
    print(f"  stand-in avatar: {len(SLOT_LOOKS)} player models, "
          f"{len(copies) - len(SLOT_LOOKS)} AI racer models ({builds} slim or heavy), "
          f"{len(parts)} face parts")


def main(src, out, preview_dir=None):
    if preview_dir:
        os.makedirs(preview_dir, exist_ok=True)
    pak = tongaspak.Pak.load(src)
    if f"{ART}/{player_cfg(0)}" in pak.index:
        raise RuntimeError(f"{src} is already modded; unpack the game's original data.pak again.")
    apply_mod(pak, preview_dir)
    pak.save(out)
    print(f"done: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the Doritos Crash Course 2 data.pak for Xenia.")
    ap.add_argument("data_pak", help="the game's original data.pak")
    ap.add_argument("out", help="modded data.pak to write")
    ap.add_argument("--preview", help="folder for the generated face and body textures")
    a = ap.parse_args()
    main(a.data_pak, a.out, a.preview)
