"""Pose the stand-in avatar with a frame of one of its Cal3D animations.

The game's .caf files are Cal3D version 1010 with one extra int after the
version: 0 for plain keyframes (time, translation, rotation per bone), 2
when a root motion track (count, then time and xyz per key) comes first.
The root motion only moves the character along the track, so it is
skipped. Cal3D rotates a vector v by quaternion q as q* v q, and combines a
bone's rotation r with its parent's absolute rotation p as r * p.
"""
import copy
import struct

import numpy as np


def read_caf(data):
    """(duration, {bone id: keyframes as rows of t, tx, ty, tz, qx, qy, qz, qw})."""
    if data[:4] != b"CAF\0":
        raise ValueError("not a CAF file")
    version, layout = struct.unpack_from("<II", data, 4)
    if version != 1010 or layout not in (0, 2):
        raise ValueError(f"unsupported CAF version {version} layout {layout}")
    p = 12
    if layout == 2:
        p += 4 + 16 * struct.unpack_from("<I", data, p)[0]
    duration, ntracks = struct.unpack_from("<fI", data, p)
    p += 8
    tracks = {}
    for _ in range(ntracks):
        bone, nkeys = struct.unpack_from("<II", data, p)
        p += 8
        tracks[bone] = np.frombuffer(data, "<f4", nkeys * 8, p).reshape(nkeys, 8)
        p += nkeys * 32
    if p != len(data):
        raise ValueError(f"parsed {p} of {len(data)} bytes")
    return duration, tracks


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def _rot(q):
    """Matrix of Cal3D's rotation by q (the usual rotation by conj(q))."""
    x, y, z, w = -q[0], -q[1], -q[2], q[3]
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def bone_transforms(skeleton, tracks, time):
    """Per bone (matrix, translation) taking bind-pose vertices to the pose."""
    bones = skeleton["bones"]
    n = len(bones)
    ra, ta = [None] * n, [None] * n
    M, T = np.zeros((n, 3, 3)), np.zeros((n, 3))
    todo = [i for i, b in enumerate(bones) if b["parent"] < 0]
    while todo:
        i = todo.pop()
        b = bones[i]
        if i in tracks:
            key = tracks[i][np.abs(tracks[i][:, 0] - time).argmin()]
            t, q = key[1:4], key[4:8] / np.linalg.norm(key[4:8])
        else:
            t, q = np.array(b["t"]), np.array(b["q"])
        par = b["parent"]
        if par < 0:
            ra[i], ta[i] = q, t
        else:
            ra[i] = _qmul(q, ra[par])
            ta[i] = _rot(ra[par]) @ t + ta[par]
        M[i] = _rot(_qmul(np.array(b["qbs"]), ra[i]))
        T[i] = _rot(ra[i]) @ np.array(b["tbs"]) + ta[i]
        todo += b["children"]
    return M, T


def pose(mesh, skeleton, tracks, time):
    """Copy of the mesh with every vertex skinned to the animation frame."""
    M, T = bone_transforms(skeleton, tracks, time)
    out = copy.deepcopy(mesh)
    for sm in out["submeshes"]:
        for v in sm["verts"]:
            ids = np.array([i for i, _ in v["infl"]])
            w = np.array([w for _, w in v["infl"]])
            w = w / w.sum()
            p, n = np.array(v["pos"]), np.array(v["nrm"])
            v["pos"] = tuple((w[:, None] * (M[ids] @ p + T[ids])).sum(0))
            n = (w[:, None] * (M[ids] @ n)).sum(0)
            v["nrm"] = tuple(n / (np.linalg.norm(n) + 1e-9))
    return out
