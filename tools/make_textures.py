"""Stand-in avatar textures (both games, same UV layout): the body in a Look's
colours and the eyes, brows and mouth of its Face.

Face features are drawn into `rect`: where the mesh's original 0..1 UV square
lands once the build normalises the face UVs.
"""
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw

WHITE, BLACK = (240, 240, 235), (30, 30, 34)
JEANS, KHAKI, GREY = (32, 53, 108), (178, 150, 102), (105, 105, 112)
BROWN = (73, 44, 10)  # hair and shoes in the original body atlas
BLOND, GINGER = (212, 166, 82), (160, 72, 28)

IRIS_COLOURS = {"brown": (118, 78, 40), "dark": (64, 40, 22), "blue": (66, 118, 182),
                "green": (88, 132, 68), "grey": (118, 124, 132), "hazel": (146, 112, 58)}
BROW_COLOURS = {"dark brown": (62, 38, 16), "black": (24, 20, 18), "brown": (110, 70, 34),
                "blond": (150, 110, 50), "ginger": (120, 52, 22)}
LIP_COLOURS = {"dark": (84, 30, 28), "red": (150, 40, 44), "pink": (178, 92, 92),
               "brown": (110, 62, 44)}


class MouthShape(NamedTuple):
    half_width: float
    height: float
    corner_lift: float
    thickness: float
    right_lift: float  # lift of the right corner over the left
    teeth: bool


class BrowShape(NamedTuple):
    arch: float
    height: float
    thickness: float


MOUTH_SHAPES = {"smile": MouthShape(0.23, 0.44, 0.07, 0.07, 0.0, False),
                "grin": MouthShape(0.27, 0.42, 0.09, 0.15, 0.0, True),
                "small": MouthShape(0.15, 0.45, 0.04, 0.06, 0.0, False),
                "smirk": MouthShape(0.21, 0.45, 0.03, 0.06, 0.07, False)}
BROW_SHAPES = {"arch": BrowShape(0.16, 0.60, 1.0), "raised": BrowShape(0.20, 0.53, 1.0),
               "straight": BrowShape(0.05, 0.57, 1.0), "thick": BrowShape(0.12, 0.60, 1.6),
               "thin": BrowShape(0.16, 0.60, 0.55)}


class Face(NamedTuple):
    """Shapes are keys of BROW_SHAPES and MOUTH_SHAPES; eye_tilt lifts the outer corners."""
    iris: tuple = IRIS_COLOURS["brown"]
    eye_size: float = 1.0
    eye_tilt: float = 0.0
    brow_shape: str = "arch"
    brow_colour: tuple = BROW_COLOURS["dark brown"]
    mouth_shape: str = "smile"
    lip_colour: tuple = LIP_COLOURS["dark"]


class Look(NamedTuple):
    """A stand-in's colours. pattern (PATTERNS) is drawn on the shirt in trim."""
    shirt: tuple
    pattern: str = "plain"
    trim: tuple = WHITE
    trousers: tuple = JEANS
    shoes: tuple = BROWN
    hair: tuple = BROWN
    skin: tuple = (203, 164, 105)
    face: Face = Face()


STAND_IN = Look((195, 200, 38))  # the original atlas: yellow shirt, jeans

# Per shirt colour (shared by both games): pattern, colours and face, so
# players differ from any side.
PLAYER_STYLES = {
    "green": dict(pattern="band", shoes=WHITE,
                  face=Face(iris=IRIS_COLOURS["green"], brow_shape="raised", mouth_shape="grin")),
    "red": dict(pattern="stripes", trousers=BLACK, shoes=WHITE, hair=BLACK,
                face=Face(iris=IRIS_COLOURS["dark"], eye_size=0.9, brow_shape="thick",
                          brow_colour=BROW_COLOURS["black"], mouth_shape="smirk",
                          lip_colour=LIP_COLOURS["brown"])),
    "blue": dict(pattern="sleeves", trousers=KHAKI, hair=BLOND,
                 face=Face(iris=IRIS_COLOURS["blue"], eye_size=1.15, brow_shape="thin",
                           brow_colour=BROW_COLOURS["blond"], mouth_shape="small",
                           lip_colour=LIP_COLOURS["pink"])),
    "yellow": dict(pattern="stripe", trim=BLACK, trousers=GREY, shoes=BLACK, hair=GINGER,
                   face=Face(iris=IRIS_COLOURS["hazel"], eye_tilt=0.03, brow_shape="straight",
                             brow_colour=BROW_COLOURS["ginger"], lip_colour=LIP_COLOURS["red"])),
}
PLAYER_STYLES["purple"] = dict(PLAYER_STYLES["yellow"], trim=(250, 200, 30))


def player_look(shirt, style):
    return Look(shirt, **PLAYER_STYLES[style])


# CC1 players by look number (race slot / HUD colour).
PLAYER_LOOKS = {
    1: player_look((35, 105, 225), "blue"),
    2: player_look((210, 25, 30), "red"),
    3: player_look((60, 185, 40), "green"),
    4: player_look((245, 190, 20), "yellow"),
}


SS = 4  # supersampling factor for smooth edges

LASH = (38, 24, 14, 255)


class _Square:
    """Draw in the original 0..1 UV square (x right, y down). u=0 is the outer
    side of each eye/brow (left and right are mirrored)."""

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


def _eye_shape(x, size=1.0, tilt=0.0):
    """Upper and lower lid y at x; size scales the opening, tilt > 0 lifts the outer corner."""
    t = (x - (EYE_X0 + EYE_X1) / 2) / ((EYE_X1 - EYE_X0) / 2)  # -1 outer .. 1 inner
    bulge = max(0.0, 1 - t * t)
    top = 0.41 - 0.12 * size * bulge + 0.015 * t + tilt * t
    bottom = 0.62 + 0.07 * size * bulge ** 1.5 + tilt * t * 0.5
    return top, bottom


def _shade(rgb, k):
    return tuple(int(c * k) for c in rgb)


def eye(size, rect, face=Face()):
    sq = _Square(size, rect)

    def shape(x):
        return _eye_shape(x, face.eye_size, face.eye_tilt)

    top = _curve(EYE_X0, EYE_X1, 48, lambda x: shape(x)[0])
    bottom = _curve(EYE_X1, EYE_X0, 48, lambda x: shape(x)[1])
    outline = top + bottom
    # White, iris and pupil, clipped to the almond.
    eye_img = Image.new("RGBA", sq.img.size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(eye_img)
    ed.rectangle((0, 0, *eye_img.size), fill=(242, 240, 234, 255))
    cx, cy, r = 0.52, 0.51, 0.17 * (0.9 + 0.1 * face.eye_size)
    ed.ellipse(sq.box(cx - r, cy - r, cx + r, cy + r), fill=(*_shade(face.iris, 0.5), 255))  # rim
    ri = r * 0.86
    ed.ellipse(sq.box(cx - ri, cy - ri, cx + ri, cy + ri), fill=(*face.iris, 255))           # iris
    rj = r * 0.55
    ed.ellipse(sq.box(cx - rj, cy - rj, cx + rj, cy + rj),
               fill=(*_shade(face.iris, 0.78), 255))                             # inner iris
    rp = r * 0.42
    ed.ellipse(sq.box(cx - rp, cy - rp, cx + rp, cy + rp), fill=(12, 10, 10, 255))   # pupil
    for gx, gy, gr in ((cx + 0.05, cy - 0.06, 0.04), (cx - 0.045, cy + 0.05, 0.018)):
        ed.ellipse(sq.box(gx - gr, gy - gr, gx + gr, gy + gr), fill=(255, 255, 255, 255))
    shadow = _curve(EYE_X0, EYE_X1, 48, lambda x: shape(x)[0] + 0.05)
    ed.polygon([sq.p(x, y) for x, y in top + shadow[::-1]], fill=(150, 140, 135, 120))
    mask = Image.new("L", sq.img.size, 0)
    ImageDraw.Draw(mask).polygon([sq.p(x, y) for x, y in outline], fill=255)
    sq.img.paste(eye_img, (0, 0), mask)
    # Upper lash line, thicker at the outer corner (small x).
    def lid(x):
        return shape(min(max(x, EYE_X0), EYE_X1))[0]

    lash_top = _curve(EYE_X0 - 0.04, EYE_X1 + 0.02, 48,
                      lambda x: lid(x) - 0.025 - 0.035 * max(0.0, (EYE_X0 + 0.12 - x) / 0.16))
    lash_bottom = _curve(EYE_X1 + 0.02, EYE_X0 - 0.04, 48, lambda x: lid(x) + 0.015)
    sq.poly(lash_top + lash_bottom, LASH)
    return sq.done()


def mouth(size, rect, face=Face()):
    # Crescent, thickest in the middle, corners up.
    sq = _Square(size, rect)
    w, ym, lift, thick, skew, teeth = MOUTH_SHAPES[face.mouth_shape]

    def edge(x, k):
        t = (x - 0.5) / w
        return ym - lift * t * t - skew * t + k * thick * (1 - t * t)

    upper = _curve(0.5 - w, 0.5 + w, 40, lambda x: edge(x, -0.5))
    lower = _curve(0.5 + w, 0.5 - w, 40, lambda x: edge(x, 0.6))
    sq.poly(upper + lower, (*face.lip_colour, 255))
    if teeth:
        top = _curve(0.5 - w * 0.8, 0.5 + w * 0.8, 30, lambda x: edge(x, -0.3))
        bottom = _curve(0.5 + w * 0.8, 0.5 - w * 0.8, 30, lambda x: edge(x, 0.05))
        sq.poly(top + bottom, (238, 234, 222, 255))
    # Lower-lip shadow.
    lip_t = _curve(0.5 - w * 0.45, 0.5 + w * 0.45, 20, lambda x: edge(x, 0.6) + 0.05)
    lip_b = _curve(0.5 + w * 0.45, 0.5 - w * 0.45, 20,
                   lambda x: edge(x, 0.6) + 0.05 + 0.025 * (1 - ((x - 0.5) / (w * 0.45)) ** 2))
    sq.poly(lip_t + lip_b, (150, 92, 70, 170))
    return sq.done()


def brow(size, rect, face=Face()):
    # Arch, thick at the inner end (large x), tapering outwards.
    sq = _Square(size, rect)
    x0, x1 = 0.10, 0.86
    arch, height, thick = BROW_SHAPES[face.brow_shape]

    def mid(x):
        t = (x - x0) / (x1 - x0)
        return height - arch * (1 - (2 * t - 1) ** 2) - 0.03 * t

    def half(x):
        t = min(max((x - x0) / (x1 - x0), 0.0), 1.0)
        return (0.022 + 0.06 * t ** 0.8) * thick

    top = _curve(x0, x1, 40, lambda x: mid(x) - half(x))
    bottom = _curve(x1, x0, 40, lambda x: mid(x) + half(x))
    sq.poly(top + bottom, (*face.brow_colour, 255))
    return sq.done()


# Per face group (avatar.FACE_GROUPS).
FACE_DRAW = {"eye": eye, "mouth": mouth, "brow": brow}


# Body atlas layout (both games), pixels of 256x256, x right, y down; the
# rest is skin. Shirt and trousers are front projections, backs mirrored onto
# the same area; shirt middle at x = 64.
BODY_REGIONS = {
    "shirt": [(68, 2), (82, 2), (96, 6), (114, 6), (120, 8), (130, 18), (136, 30), (132, 48),
              (128, 52), (100, 60), (96, 68), (96, 86), (108, 106), (100, 118), (24, 116),
              (22, 112), (28, 66), (4, 58), (0, 16), (16, 8), (44, 10), (66, 4)],
    "trousers": [(32, 120), (94, 120), (108, 138), (118, 172), (120, 214), (126, 230),
                 (124, 246), (118, 256), (12, 256), (6, 250), (2, 242), (6, 158)],
    "hair": [(106, 90), (106, 72), (118, 56), (132, 50), (162, 52), (166, 66), (174, 84),
             (166, 106), (154, 116), (142, 120), (124, 118), (108, 98)],
    "shoes": [(164, 12), (168, 2), (170, 0), (254, 0), (256, 84), (242, 88), (176, 84),
              (166, 66), (162, 52)],
}
# Shirt patterns: boxes (x0, y0, x1, y1), symmetric so front and back match.
PATTERNS = {
    "plain": [],
    "band": [(0, 34, 136, 54)],                                    # chest band
    "stripes": [(0, y, 136, y + 7) for y in range(24, 118, 16)],   # hoops
    "sleeves": [(0, 0, 34, 70), (102, 0, 136, 70), (52, 0, 76, 12)],  # sleeves, collar
    "stripe": [(55, 0, 73, 118)],                                  # racing stripe
}


def body(size, look=STAND_IN):
    """Body texture in a look's colours."""
    sx, sy = size[0] * SS / 256, size[1] * SS / 256
    img = Image.new("RGB", (size[0] * SS, size[1] * SS), look.skin)
    draw = ImageDraw.Draw(img)
    for name, outline in BODY_REGIONS.items():
        draw.polygon([(x * sx, y * sy) for x, y in outline], fill=getattr(look, name))
    if PATTERNS[look.pattern]:
        trim = Image.new("RGB", img.size, look.trim)
        mask = Image.new("L", img.size, 0)
        mdraw = ImageDraw.Draw(mask)
        for x0, y0, x1, y1 in PATTERNS[look.pattern]:
            mdraw.rectangle((x0 * sx, y0 * sy, x1 * sx, y1 * sy), fill=255)
        shirt = Image.new("L", img.size, 0)
        ImageDraw.Draw(shirt).polygon([(x * sx, y * sy) for x, y in BODY_REGIONS["shirt"]],
                                      fill=255)
        img.paste(trim, (0, 0), Image.fromarray(np.minimum(np.asarray(mask),
                                                           np.asarray(shirt))))
    # Supersampled: smooth edges, sharp patterns (no blur).
    return img.resize(size, Image.LANCZOS)
