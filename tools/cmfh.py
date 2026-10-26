"""CC2's baked Cal3D mesh (.cmfh).

Big-endian: "CHM\\0", version, vertex count, triangle count; 80-byte vertices (20 floats:
position, 4 weights, 4 bone indices, normal, tangent + sign, UV); u16 indices (submesh-local);
submesh table (first vertex, vertex count, first index, triangle count, material, bone palette).
Bone indices index the submesh's palette. The body is several submeshes (material 5, one per
palette); vertices on their seams are duplicated.
"""
import struct

import numpy as np

STRIDE = 20  # floats per vertex
POS, WEIGHTS, BONES, NRM, UV = slice(0, 3), slice(3, 7), slice(7, 11), slice(11, 14), slice(18, 20)


class Mesh:
    def __init__(self, data):
        if data[:4] != b"CHM\0":
            raise ValueError("not a .cmfh mesh")
        self.data = bytearray(data)
        nv, nt = struct.unpack_from(">II", data, 8)
        self.verts = np.frombuffer(bytes(data[16:16 + nv * STRIDE * 4]), ">f4") \
            .reshape(nv, STRIDE).astype(np.float64)
        self.idx_at = 16 + nv * STRIDE * 4
        self.indices = np.frombuffer(bytes(data[self.idx_at:self.idx_at + nt * 6]),
                                     ">u2").astype(np.int64)
        p = self.idx_at + nt * 6
        count, = struct.unpack_from(">I", data, p)
        p += 4
        self.submeshes = []
        for _ in range(count):
            v0, nverts, i0, ntris, material, nbones = struct.unpack_from(">6I", data, p)
            palette = list(struct.unpack_from(f">{nbones}I", data, p + 24))
            p += 24 + 4 * nbones
            self.submeshes.append({"first_vertex": v0, "verts": nverts, "first_index": i0,
                                   "tris": ntris, "material": material, "palette": palette})
        if len(data) - p != 2:  # two bytes of unknown meaning end the file
            raise ValueError(f"parsed {p} of {len(data)} bytes")

    def submesh(self, i):
        """(vertex rows, triangles with submesh-local vertex numbers)."""
        s = self.submeshes[i]
        return self.verts[s["first_vertex"]:s["first_vertex"] + s["verts"]], self._tris(s)

    def _tris(self, s):
        """Submesh `s`'s triangles: a writable view into the index buffer."""
        return self.indices[s["first_index"]:s["first_index"] + 3 * s["tris"]].reshape(-1, 3)

    def set_uvs(self, i, uv):
        s = self.submeshes[i]
        self.verts[s["first_vertex"]:s["first_vertex"] + s["verts"], UV] = uv

    def rows(self, ids):
        """Global vertex numbers of the submeshes' vertices, in order."""
        return np.concatenate([np.arange(self.submeshes[i]["verts"])
                               + self.submeshes[i]["first_vertex"] for i in ids])

    def _palette_of_rows(self, ids):
        """Per vertex (rows order): index in `ids` of its submesh."""
        return np.concatenate([np.full(self.submeshes[i]["verts"], k) for k, i in enumerate(ids)])

    def merged(self, ids):
        """The submeshes as one cal3d.read_cmf-style submesh (seam copies welded, skeleton
        bone numbers). Returns it and each vertex's welded number."""
        rows = self.rows(ids)
        v = self.verts[rows]
        key = np.round(np.hstack([v[:, POS], v[:, UV]]), 6)
        _, first, welded = np.unique(key, axis=0, return_index=True, return_inverse=True)
        welded = welded.ravel()
        pal_of_row = self._palette_of_rows(ids)
        verts = []
        for r in first:
            pal = self.submeshes[ids[pal_of_row[r]]]["palette"]
            infl = [(pal[int(b)], float(w)) for w, b in zip(v[r, WEIGHTS], v[r, BONES]) if w > 0]
            verts.append({"pos": tuple(v[r, POS]), "nrm": tuple(v[r, NRM]),
                          "uv": [tuple(v[r, UV])], "infl": infl})
        faces, base = [], 0
        for i in ids:
            _, tris = self.submesh(i)
            faces += [tuple(int(welded[base + x]) for x in t) for t in tris]
            base += self.submeshes[i]["verts"]
        return {"verts": verts, "faces": faces, "springs": [], "nlod": 0}, welded

    def set_merged(self, ids, before, after, welded, drop):
        """Write a changed merged() back: moves and weights per welded vertex (bones outside
        the palette dropped), `drop` faces degenerate. Returns how many vertices lost a bone."""
        rows = self.rows(ids)
        pal_of_row = self._palette_of_rows(ids)
        lost = 0
        for r, w, k in zip(rows, welded, pal_of_row):
            b, a = before["verts"][w], after["verts"][w]
            self.verts[r, POS] += np.subtract(a["pos"], b["pos"])
            if a["infl"] == b["infl"]:
                continue
            pal = self.submeshes[ids[k]]["palette"]
            infl = [(pal.index(bone), wt) for bone, wt in a["infl"] if bone in pal]
            lost += len(infl) < len(a["infl"])
            total = sum(wt for _, wt in infl)
            infl += [(0, 0.0)] * (4 - len(infl))
            self.verts[r, BONES] = [bone for bone, _ in infl]
            self.verts[r, WEIGHTS] = [wt / total for _, wt in infl]
        n = 0
        for i in ids:
            s = self.submeshes[i]
            tris = self._tris(s)
            tris[drop[n:n + s["tris"]]] = tris[drop[n:n + s["tris"]], :1]
            n += s["tris"]
        return lost

    def serialize(self):
        out = bytearray(self.data)
        n = len(self.verts)
        out[16:16 + n * STRIDE * 4] = self.verts.astype(">f4").tobytes()
        out[self.idx_at:self.idx_at + 2 * len(self.indices)] = self.indices.astype(">u2").tobytes()
        return bytes(out)
