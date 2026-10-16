"""Stand-in avatar textures for the Doritos Crash Course mod.

The Xbox build of the game ships the PC-era dummy avatar mesh and its body
texture, but none of the face textures or shaders it needs. Face features
are drawn into `rect`, the part of the texture that the mesh's original
0..1 UV square maps to after build_mod.py normalises the face UVs.
"""
import numpy as np
from PIL import Image, ImageDraw

SHIRT = (195, 200, 38)  # yellow shirt in the original body atlas

# The game's own player colours (lobby slots / HUD), one per controller slot.
PLAYER_SHIRTS = {
    1: (35, 105, 225),   # blue
    2: (210, 25, 30),    # red
    3: (60, 185, 40),    # green
    4: (245, 190, 20),   # yellow
}


def recolor_shirt(body, colour):
    a = np.asarray(body.convert("RGB")).astype(np.int32)
    dist = np.abs(a - np.array(SHIRT)).sum(axis=2)
    # Soft mask so JPEG-blurred edges blend instead of leaving a yellow rim.
    w = np.clip(1.0 - (dist - 40) / 60.0, 0.0, 1.0)[..., None]
    out = a * (1 - w) + np.array(colour) * w
    return Image.fromarray(out.astype(np.uint8))


SS = 4  # supersampling factor for smooth edges

LASH = (38, 24, 14, 255)
HAIR = (62, 38, 16, 255)


class _Square:
    """Draw in the texture's original 0..1 UV square (x right, y down).

    Texture u=0 is the outer side of each eye/brow (left and right parts are
    mirrored), v=0 is up.
    """

    def __init__(self, size, rect):
        self.size = size
        self.img = Image.new("RGBA", (size[0] * SS, size[1] * SS), (255, 255, 255, 0))
        self.draw = ImageDraw.Draw(self.img)
        x0, y0, x1, y1 = rect
        self.origin = (x0 * SS, y0 * SS)
        self.span = ((x1 - x0) * SS, (y1 - y0) * SS)

    def p(self, x, y):
        return (self.origin[0] + self.span[0] * x, self.origin[1] + self.span[1] * y)

    def box(self, x0, y0, x1, y1):
        return (*self.p(x0, y0), *self.p(x1, y1))

    def poly(self, pts, fill):
        self.draw.polygon([self.p(x, y) for x, y in pts], fill=fill)

    def done(self):
        return self.img.resize(self.size, Image.LANCZOS)


def _curve(x0, x1, n, f):
    return [(x0 + (x1 - x0) * i / n, f(x0 + (x1 - x0) * i / n)) for i in range(n + 1)]


EYE_X0, EYE_X1 = 0.27, 0.75  # almond extent in the eye's UV square


def _eye_shape(x):
    """Upper and lower lid y at x for the almond eye."""
    t = (x - (EYE_X0 + EYE_X1) / 2) / ((EYE_X1 - EYE_X0) / 2)  # -1 outer .. 1 inner
    bulge = max(0.0, 1 - t * t)
    top = 0.41 - 0.12 * bulge + 0.015 * t
    bottom = 0.62 + 0.07 * bulge ** 1.5
    return top, bottom


def eye(size, rect):
    sq = _Square(size, rect)
    top = _curve(EYE_X0, EYE_X1, 48, lambda x: _eye_shape(x)[0])
    bottom = _curve(EYE_X1, EYE_X0, 48, lambda x: _eye_shape(x)[1])
    outline = top + bottom
    # White, iris and pupil, clipped to the almond by drawing into a mask.
    eye_img = Image.new("RGBA", sq.img.size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(eye_img)
    ed.rectangle((0, 0, *eye_img.size), fill=(242, 240, 234, 255))
    cx, cy, r = 0.52, 0.51, 0.17
    ed.ellipse(sq.box(cx - r, cy - r, cx + r, cy + r), fill=(58, 36, 18, 255))      # rim
    ri = r * 0.86
    ed.ellipse(sq.box(cx - ri, cy - ri, cx + ri, cy + ri), fill=(118, 78, 40, 255))  # iris
    rj = r * 0.55
    ed.ellipse(sq.box(cx - rj, cy - rj, cx + rj, cy + rj), fill=(92, 58, 28, 255))   # inner iris
    rp = r * 0.42
    ed.ellipse(sq.box(cx - rp, cy - rp, cx + rp, cy + rp), fill=(12, 10, 10, 255))   # pupil
    for gx, gy, gr in ((cx + 0.05, cy - 0.06, 0.04), (cx - 0.045, cy + 0.05, 0.018)):
        ed.ellipse(sq.box(gx - gr, gy - gr, gx + gr, gy + gr), fill=(255, 255, 255, 255))
    # Soft shadow under the upper lid.
    shadow = _curve(EYE_X0, EYE_X1, 48, lambda x: _eye_shape(x)[0] + 0.05)
    ed.polygon([sq.p(x, y) for x, y in top + shadow[::-1]], fill=(150, 140, 135, 120))
    mask = Image.new("L", sq.img.size, 0)
    ImageDraw.Draw(mask).polygon([sq.p(x, y) for x, y in outline], fill=255)
    sq.img.paste(eye_img, (0, 0), mask)
    # Upper lash line, thicker towards the outer corner (x small).
    def lid(x):
        return _eye_shape(min(max(x, EYE_X0), EYE_X1))[0]

    lash_top = _curve(EYE_X0 - 0.04, EYE_X1 + 0.02, 48,
                      lambda x: lid(x) - 0.025 - 0.035 * max(0.0, (EYE_X0 + 0.12 - x) / 0.16))
    lash_bottom = _curve(EYE_X1 + 0.02, EYE_X0 - 0.04, 48, lambda x: lid(x) + 0.015)
    sq.poly(lash_top + lash_bottom, LASH)
    return sq.done()


def mouth(size, rect):
    # Closed smile: a crescent, thickest in the middle, corners turned up.
    sq = _Square(size, rect)
    w, ym, lift, thick = 0.23, 0.44, 0.07, 0.07

    def edge(x, k):
        t = (x - 0.5) / w
        return ym - lift * t * t + k * thick * (1 - t * t)

    upper = _curve(0.5 - w, 0.5 + w, 40, lambda x: edge(x, -0.5))
    lower = _curve(0.5 + w, 0.5 - w, 40, lambda x: edge(x, 0.6))
    sq.poly(upper + lower, (84, 30, 28, 255))
    # Short lower-lip shadow.
    lip_t = _curve(0.5 - w * 0.45, 0.5 + w * 0.45, 20, lambda x: edge(x, 0.6) + 0.05)
    lip_b = _curve(0.5 + w * 0.45, 0.5 - w * 0.45, 20,
                   lambda x: edge(x, 0.6) + 0.05 + 0.025 * (1 - ((x - 0.5) / (w * 0.45)) ** 2))
    sq.poly(lip_t + lip_b, (150, 92, 70, 170))
    return sq.done()


def brow(size, rect):
    # Gentle arch, thick at the inner end (x large), tapering outwards.
    sq = _Square(size, rect)
    x0, x1 = 0.10, 0.86

    def mid(x):
        t = (x - x0) / (x1 - x0)
        return 0.60 - 0.16 * (1 - (2 * t - 1) ** 2) - 0.03 * t

    def half(x):
        t = min(max((x - x0) / (x1 - x0), 0.0), 1.0)
        return 0.022 + 0.06 * t ** 0.8

    top = _curve(x0, x1, 40, lambda x: mid(x) - half(x))
    bottom = _curve(x1, x0, 40, lambda x: mid(x) + half(x))
    sq.poly(top + bottom, HAIR)
    return sq.done()
