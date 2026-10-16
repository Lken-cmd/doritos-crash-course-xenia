"""Tiny orthographic software renderer for the stand-in avatar.

Used for the preview image and for the track billboard pictures.
"""
import numpy as np

from avatar import BODY

FACE_SUBMESHES = BODY  # submeshes before the body (face parts) sit just in front of it


def render(mesh, texs, W=240, H=420, yaw=0.0, squash=1.0, bg=(40, 40, 40), ambient=0.45):
    """Orthographic render, the model's +Y away from the camera and Z up.

    yaw turns the model (degrees), squash scales the image horizontally,
    bg=None gives a transparent background, and ambient is the light level
    of surfaces facing away from the light. Returns an RGBA array."""
    allp = np.array([v["pos"] for sm in mesh["submeshes"] for v in sm["verts"]])
    lo, hi = allp.min(0), allp.max(0)
    span = (hi[2] - lo[2]) * 1.05
    mid = (hi + lo) / 2
    a = np.radians(yaw)
    rot = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    img = np.zeros((H, W, 4))
    if bg is not None:
        img[...] = (*bg, 255)
    zbuf = np.full((H, W), -np.inf)
    light = np.array([0.3, -0.8, 0.5]) / np.linalg.norm([0.3, -0.8, 0.5])
    for si, sm in enumerate(mesh["submeshes"]):
        t = texs[si].astype(np.float32)
        th, tw = t.shape[:2]
        P = (np.array([v["pos"] for v in sm["verts"]]) - mid) @ rot.T
        N = np.array([v["nrm"] for v in sm["verts"]]) @ rot.T
        UV = np.array([v["uv"][0] for v in sm["verts"]])
        sx = P[:, 0] / span * H * squash + W / 2
        sy = H / 2 - P[:, 2] / span * H
        sz = -P[:, 1] + (0.002 if si < FACE_SUBMESHES else 0)
        for f in sm["faces"]:
            f = list(f)
            xs, ys = sx[f], sy[f]
            x0, x1 = int(max(xs.min(), 0)), int(min(xs.max() + 1, W))
            y0, y1 = int(max(ys.min(), 0)), int(min(ys.max() + 1, H))
            if x0 >= x1 or y0 >= y1:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1) + .5, np.arange(y0, y1) + .5)
            d = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(d) < 1e-9:
                continue
            l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / d
            l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / d
            l2 = 1 - l0 - l1
            inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            z = l0 * sz[f[0]] + l1 * sz[f[1]] + l2 * sz[f[2]]
            # Wrap addressing: the worst case for the face UVs.
            u = (l0 * UV[f[0], 0] + l1 * UV[f[1], 0] + l2 * UV[f[2], 0]) % 1.0
            v = (l0 * UV[f[0], 1] + l1 * UV[f[1], 1] + l2 * UV[f[2], 1]) % 1.0
            ti = np.clip((v * th).astype(int), 0, th - 1)
            tj = np.clip((u * tw).astype(int), 0, tw - 1)
            texel = t[ti, tj]
            ok = inside & (texel[..., 3] >= 128) & (z > zbuf[y0:y1, x0:x1])
            n = N[f].sum(0)
            n /= np.linalg.norm(n) + 1e-9
            shade = ambient + (1 - ambient) * max(0.0, -(n @ light)) if si >= BODY else 1.0
            zbuf[y0:y1, x0:x1][ok] = z[ok]
            img[y0:y1, x0:x1][ok] = np.concatenate(
                [texel[..., :3][ok] * shade, np.full((ok.sum(), 1), 255.0)], 1)
    return np.clip(img, 0, 255).astype(np.uint8)
