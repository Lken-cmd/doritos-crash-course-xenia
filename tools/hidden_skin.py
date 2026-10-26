"""Keep the stand-in's bare body from poking through its clothes.

dummymodel.cmf: a full bare body plus garment shells (shirt, trousers,
shoes, hair) in one submesh, garments bound to other bones than the body
under them. fit_clothes():
1. binds every garment vertex like the body under it,
2. tucks covered skin inwards, deeper away from the hems (TUCK),
3. drops body triangles deep under a garment (as the Xbox avatar system
   does), keeping HEM_MARGIN next to exposed skin so a lifting hem shows skin.
"""
import numpy as np

MAX_DIST = 0.06    # skin -> garment distance along the normal, in metres
BACK_DIST = 0.01   # also count garments that already cut into the skin
HEM_MARGIN = 0.07  # keep covered skin this close to exposed skin
# Tuck depth: TUCK + TUCK_SLOPE per metre from exposed skin, up to TUCK_MAX.
TUCK, TUCK_SLOPE, TUCK_MAX = 0.005, 0.6, 0.04
# Always covered (the normal test misses the crotch: trousers sit higher).
COVERED_BONES = {"BASE", "SC_BASE", "LF_SC_H", "RT_SC_H", "BACKA", "BACKB",
                 "SC_BACKA", "SC_BACKB", "LF_C", "RT_C", "LF_SC_S", "RT_SC_S"}
# Never removed (the collar gapes when the head moves), only tucked.
KEEP_BONES = {"NECK", "SC_NECK", "HEAD"}
# Pieces mostly on this bone (face, hair, head) aren't clothes.
HEAD_BONE = "HEAD"


def _components(faces, nverts):
    parent = list(range(nverts))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b, c in faces:
        parent[find(a)] = find(b)
        parent[find(c)] = find(b)
    return np.array([find(i) for i in range(nverts)])


def _cast(orig, dirs, v0, e1, e2, t_max):
    """Whether each ray hits one of the triangles within t_max."""
    hit = np.zeros(len(orig), bool)
    for s in range(0, len(orig), 256):
        o, d = orig[s:s + 256, None], dirs[s:s + 256, None]
        p = np.cross(d, e2)
        det = (e1 * p).sum(-1)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1 / det
            tv = o - v0
            u = (tv * p).sum(-1) * inv
            q = np.cross(tv, e1)
            v = (d * q).sum(-1) * inv
            t = (e2 * q).sum(-1) * inv
        ok = (np.abs(det) > 1e-12) & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= t_max)
        hit[s:s + 256] = ok.any(1)
    return hit


def _nearest_dist(pts, targets):
    best = np.full(len(pts), np.inf)
    for s in range(0, len(pts), 256):
        d = np.linalg.norm(pts[s:s + 256, None] - targets[None], axis=-1)
        best[s:s + 256] = d.min(1)
    return best


class _Layers:
    """Which faces are body, garment or head, and which body skin is covered."""

    def __init__(self, sm, bone_names):
        if sm["springs"] or sm["nlod"]:
            raise ValueError("submesh has springs or LOD data")
        self.F = F = np.array(sm["faces"])
        self.P = P = np.array([v["pos"] for v in sm["verts"]])
        self.N = N = np.array([v["nrm"] for v in sm["verts"]])
        bone = np.array([bone_names[max(v["infl"], key=lambda i: i[1])[0]] for v in sm["verts"]])
        comp = _components(sm["faces"], len(P))
        roots, sizes = np.unique(comp[F[:, 0]], return_counts=True)
        self.skin = comp[F[:, 0]] == roots[sizes.argmax()]      # largest piece: the body
        self.garment_v = np.zeros(len(P), bool)
        for c in np.unique(comp[F[~self.skin, 0]]):
            members = comp == c
            if (bone[members] == HEAD_BONE).mean() < 0.5:       # not face, hair, head
                self.garment_v |= members
        self.body_v = np.unique(F[self.skin])
        cloth = F[self.garment_v[F].all(1)]
        v0 = P[cloth[:, 0]]
        hit = _cast(P - N * BACK_DIST, N, v0, P[cloth[:, 1]] - v0, P[cloth[:, 2]] - v0,
                    MAX_DIST + BACK_DIST)
        body = np.zeros(len(P), bool)
        body[self.body_v] = True
        self.keep_v = np.isin(bone, list(KEEP_BONES))
        forced = np.isin(bone, list(COVERED_BONES))
        self.covered_v = (hit | forced) & body & (bone != HEAD_BONE)
        # Garments are closed shells: openings are where exposed skin meets covered.
        self.opening_dist = _nearest_dist(P, P[body & ~self.covered_v])

    def deep_faces(self, margin):
        deep = self.covered_v & ~self.keep_v & (self.opening_dist > margin)
        return self.skin & deep[self.F].all(1)

    def tuck_depth(self):
        d = np.minimum(TUCK + TUCK_SLOPE * self.opening_dist, TUCK_MAX)
        return np.where(self.covered_v, d, 0.0)


def _match_clothes(sm, layers, k=4, max_infl=4):
    """Copy with garment vertices weighted like their k nearest body vertices
    (inverse squared distance)."""
    P, body = layers.P, layers.body_v
    out = dict(sm)
    out["verts"] = [dict(v) for v in sm["verts"]]
    for g in np.nonzero(layers.garment_v)[0]:
        d = np.linalg.norm(P[body] - P[g], axis=1)
        near = np.argsort(d)[:k]
        mix = {}
        for j, dj in zip(body[near], d[near]):
            for b, w in sm["verts"][j]["infl"]:
                mix[b] = mix.get(b, 0.0) + w / (dj * dj + 1e-6)
        top = sorted(mix.items(), key=lambda bw: -bw[1])[:max_infl]
        total = sum(w for _, w in top)
        out["verts"][g]["infl"] = [(b, w / total) for b, w in top]
    return out


def fit(sm, bone_names):
    """(copy with fixes 1 and 2, mask of faces fix 3 drops, share of body triangles dropped)."""
    layers = _Layers(sm, bone_names)
    out = _match_clothes(sm, layers)
    out["verts"] = [dict(v, pos=tuple(np.array(v["pos"]) - np.array(v["nrm"]) * d))
                    if d else v for v, d in zip(out["verts"], layers.tuck_depth())]
    drop = layers.deep_faces(HEM_MARGIN)
    return out, drop, drop.sum() / layers.skin.sum()


def fit_clothes(sm, bone_names):
    """(copy with all three fixes, share of body triangles removed)."""
    out, drop, share = fit(sm, bone_names)
    faces = [f for f, d in zip(sm["faces"], drop) if not d]
    used = sorted({i for f in faces for i in f})
    new = {old: i for i, old in enumerate(used)}
    out["verts"] = [out["verts"][i] for i in used]
    out["faces"] = [tuple(new[i] for i in f) for f in faces]
    return out, share
