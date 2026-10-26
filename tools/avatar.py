"""Stand-in avatar layout (data/art/_avatar/dummymodel.*): submeshes and texture names."""
import io

import numpy as np
from PIL import Image

ART = "data/art"  # resource names are relative to this
AVATAR_DIR = f"{ART}/_avatar"
# Submeshes 0-4 of dummymodel.cmf; mirrored halves share one texture.
FACE_GROUPS = {"mouth": [0], "eye": [1, 2], "brow": [3, 4]}
FACE_TEX_SIZE = {"mouth": (256, 128), "eye": (256, 512), "brow": (256, 128)}
SUBMESH_SHADERS = ["mouth", "eye", "eye", "brow", "brow"]
BODY = 5  # submesh 5: body, clothes, hair and head


def res(name):
    """Resource name (templates, .mat.txt) of a file in AVATAR_DIR."""
    return "_avatar/" + name


def player_cfg(n):
    """Player model n: CC1 look 1-4, CC2 player number 0-3."""
    return res(f"player{n}.cfg")


def face_rect(name, lo, hi):
    """Pixel rect of the 0..1 UV square once the group's UV range lo..hi fills its texture."""
    w, h = FACE_TEX_SIZE[name]
    return ((0 - lo[0]) / (hi[0] - lo[0]) * w, (0 - lo[1]) / (hi[1] - lo[1]) * h,
            (1 - lo[0]) / (hi[0] - lo[0]) * w, (1 - lo[1]) / (hi[1] - lo[1]) * h)


def body_name(look):
    """Shader/texture base name of a look's body."""
    return f"body_p{look}"


def face_name(group, look):
    """Shader/texture base name of a look's face group."""
    return f"{group}_p{look}"


def textures(read, look):
    """RGBA texture per submesh of a look; read(name) gives AVATAR_DIR/<name>."""
    def img(name):
        return np.asarray(Image.open(io.BytesIO(read(name))).convert("RGBA"))

    face = {n: img(face_name(n, look) + ".png") for n in FACE_GROUPS}
    return [face[s] for s in SUBMESH_SHADERS] + [img(body_name(look) + ".jpg")]
