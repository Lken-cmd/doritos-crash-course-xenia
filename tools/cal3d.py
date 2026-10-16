"""Cal3D binary mesh (CMF) and skeleton (CSF) reader/writer, version 1010.

Doritos Crash Course stores its animated props and the stand-in avatar in
these little-endian Cal3D formats inside data.pak.
"""
import struct


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def i32(self):
        v, = struct.unpack_from("<i", self.d, self.p)
        self.p += 4
        return v

    def f32(self, n=1):
        v = struct.unpack_from(f"<{n}f", self.d, self.p)
        self.p += 4 * n
        return v if n > 1 else v[0]

    def string(self):
        n = self.i32()
        s = self.d[self.p:self.p + n].rstrip(b"\0").decode("latin-1")
        self.p += n
        return s


def read_cmf(data):
    r = _Reader(data)
    if data[:4] != b"CMF\0":
        raise ValueError("not a CMF file")
    r.p = 4
    mesh = {"version": r.i32(), "unk": r.i32(), "submeshes": []}
    for _ in range(r.i32()):
        sm = {"material": r.i32()}
        nv, nf, nlod, nspring, nmap = (r.i32() for _ in range(5))
        verts = []
        for _ in range(nv):
            v = {"pos": r.f32(3), "nrm": r.f32(3),
                 "collapse_id": r.i32(), "face_collapse_count": r.i32()}
            v["uv"] = [r.f32(2) for _ in range(nmap)]
            v["infl"] = [(r.i32(), r.f32()) for _ in range(r.i32())]
            v["phys"] = r.f32() if nspring else None
            verts.append(v)
        sm["springs"] = [(r.i32(), r.i32(), r.f32(), r.f32()) for _ in range(nspring)]
        sm["faces"] = [(r.i32(), r.i32(), r.i32()) for _ in range(nf)]
        for f in sm["faces"]:
            if not all(0 <= i < nv for i in f):
                raise ValueError(f"face {f} out of range ({nv} verts)")
        sm.update(verts=verts, nlod=nlod, nmap=nmap)
        mesh["submeshes"].append(sm)
    if r.p != len(data):
        raise ValueError(f"trailing data: parsed {r.p} of {len(data)} bytes")
    return mesh


def write_cmf(mesh):
    out = bytearray(b"CMF\0")
    out += struct.pack("<iii", mesh["version"], mesh["unk"], len(mesh["submeshes"]))
    for sm in mesh["submeshes"]:
        out += struct.pack("<6i", sm["material"], len(sm["verts"]), len(sm["faces"]),
                           sm["nlod"], len(sm["springs"]), sm["nmap"])
        for v in sm["verts"]:
            out += struct.pack("<3f3fii", *v["pos"], *v["nrm"],
                               v["collapse_id"], v["face_collapse_count"])
            for uv in v["uv"]:
                out += struct.pack("<2f", *uv)
            out += struct.pack("<i", len(v["infl"]))
            for bone, weight in v["infl"]:
                out += struct.pack("<if", bone, weight)
            if sm["springs"]:
                out += struct.pack("<f", v["phys"])
        for s in sm["springs"]:
            out += struct.pack("<iiff", *s)
        for f in sm["faces"]:
            out += struct.pack("<3i", *f)
    return bytes(out)


def read_csf(data):
    r = _Reader(data)
    if data[:4] != b"CSF\0":
        raise ValueError("not a CSF file")
    r.p = 4
    version = r.i32()
    bones = []
    for _ in range(r.i32()):
        bones.append({"name": r.string(), "t": r.f32(3), "q": r.f32(4),
                      "tbs": r.f32(3), "qbs": r.f32(4), "parent": r.i32(),
                      "children": [r.i32() for _ in range(r.i32())]})
    return {"version": version, "bones": bones}
