"""Layout of the stand-in avatar (data/art/_avatar/dummymodel.*) as the mod
uses it: which submesh is which, and the textures the build makes."""
import io

import numpy as np
from PIL import Image

AVATAR_DIR = "data/art/_avatar"
# Submeshes 0-4 of dummymodel.cmf; mirrored halves share one texture.
FACE_GROUPS = {"mouth": [0], "eye": [1, 2], "brow": [3, 4]}
FACE_TEX_SIZE = {"mouth": (256, 128), "eye": (256, 512), "brow": (256, 128)}
SUBMESH_SHADERS = ["mouth", "eye", "eye", "brow", "brow"]
BODY = 5  # submesh 5: body, clothes, hair and head


def body_name(look):
    """Shader and texture base name of a look's body (the shirt colour)."""
    return f"body_p{look}"


def textures(read, look):
    """RGBA texture per submesh of a look, in submesh order.

    read(name) returns the bytes of AVATAR_DIR/<name>."""
    def img(name):
        return np.asarray(Image.open(io.BytesIO(read(name))).convert("RGBA"))

    face = {n: img(f"{n}.png") for n in FACE_GROUPS}
    return [face[s] for s in SUBMESH_SHADERS] + [img(body_name(look) + ".jpg")]
