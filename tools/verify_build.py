"""Check a built CC1 mod (<out_dir>/game/data.pak as written) and render the
4 players to preview/players.png. Fails if an Xbox avatar (XAVT:) is left.

usage: python verify_build.py <out_dir>
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

import cal3d
import render
import tongaspak
import wbr
from avatar import AVATAR_DIR, textures


def main(out_dir):
    pak = tongaspak.Pak.load(os.path.join(out_dir, "game", "data.pak"))
    files = {name: pak.get(name) for name in pak.index}
    print(f"{len(files)} entries decompress OK")

    left = set()
    for t in ("fighter", "guiresource", "bonedmodel", "shader", "texture"):
        w = wbr.Wbr(files[f"data/templates/{t}.wbr"])
        refs = sorted({v[i] for v, i in w.values("str") if v[i][:5] in ("XAVT:", "BNMD:")})
        left |= {r for r in refs if r.startswith("XAVT:")}
        print(f"{t}.wbr: {len(w.records)} records; avatar refs: "
              f"{[r for r in refs if 'umbrella' not in r and 'props/' not in r][:6]}...")
    for name in (n for n in files if n.startswith("data/precache/")):
        left |= {line.strip() for line in files[name].decode("latin-1").split("\n")
                 if line.startswith("XAVT:")}
    boned = wbr.Wbr(files["data/templates/bonedmodel.wbr"])
    for key in ("_avatar/player1.cfg", "_avatar/player4.cfg", "_avatar/credits2.cfg"):
        _, vals = boned.record(key)
        print(f"  BNMD {key}: FileName={vals[boned.field_index('FileName')]}"
              f" ShadersList={vals[boned.field_index('ShadersList')]}")

    mesh = cal3d.read_cmf(files[f"{AVATAR_DIR}/dummymodel.cmf"])
    panels = [render.render(mesh, textures(lambda n: files[f"{AVATAR_DIR}/{n}"], p))[..., :3]
              for p in range(1, 5)]
    out = os.path.join(out_dir, "preview", "players.png")
    Image.fromarray(np.hstack(panels)).save(out)
    print("wrote", out)
    if left:
        sys.exit(f"still Xbox avatars (invisible in Xenia): {sorted(left)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Check a built mod and render the players.")
    ap.add_argument("out_dir", help="the build folder (with game/data.pak)")
    main(ap.parse_args().out_dir)
