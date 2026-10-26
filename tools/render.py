"""Orthographic software renderer for the stand-in (previews, billboard pictures)."""
import numpy as np

from avatar import BODY

FACE_SUBMESHES = BODY  # face parts, drawn just in front of the body


def frame_of(mesh):
    """(middle, height + 5%): the view render() fits a mesh into."""
    allp = np.array([v["pos"] for sm in mesh["submeshes"] for v in sm["verts"]])
    lo, hi = allp.min(0), allp.max(0)
    return (hi + lo) / 2, (hi[2] - lo[2]) * 1.05


def render(mesh, texs, W=240, H=420, yaw=0.0, squash=1.0, bg=(40, 40, 40), ambient=0.45,
           frame=None):
    """RGBA array; +Y away from the camera, Z up. yaw in degrees, squash scales
    x, bg=None is transparent, ambient lights surfaces facing away from the
    light, frame (frame_of) defaults to the mesh's own."""
    mid, span = frame or frame_of(mesh)
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
