"""Reader/writer for the engine's binary templates (*.wbr, little-endian).

Layout (inferred from the Doritos Crash Course data):
  u16 version(2), u16 class_count(1)
  u16 class_id, str class_name, u16 unk(1), u16 field_count
  field_count x (str name, u8 type)
  u16 record_count
  record_count x (u16 class_id, str key,
                  field_count x ('1' u16 n, n x value | '0'))
  trailing bytes kept verbatim
str = u32 length + bytes (no terminator).
"""
import struct

# type -> (python struct code or 'str', element count)
TYPES = {
    0x00: ("i", 1),      # int
    0x01: ("i", 1),      # enum
    0x02: ("B", 1),      # bool
    0x03: ("f", 1),      # float
    0x04: ("str", 1),    # localized text
    0x06: ("str", 1),    # string / resource ref
    0x08: ("f", 2),      # vec2
    0x09: ("f", 3),      # vec3
    0x0A: ("f", 4),      # vec4
    0x0B: ("f", 3),      # angles
    0x0C: ("3s", 1),     # RGB colour
    0x0D: ("str2", 1),   # texture ref: two strings
    0x0E: ("script", 1), # u8 kind; kind 2: u32 unk + u32 len + Lua 5.1 bytecode
}
STRING, SCRIPT = 0x06, 0x0E


class Wbr:
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.version, self.class_count = self._u16(), self._u16()
        self.class_id = self._u16()
        self.class_name = self._str()
        self.unk = self._u16()
        nfields = self._u16()
        self.fields = [(self._str(), self.d[self._adv(1)]) for _ in range(nfields)]
        for name, t in self.fields:
            if t not in TYPES:
                raise ValueError(f"{self.class_name}.{name}: unknown type {t:#x}")
        nrec = self._u16()
        self.records = []
        for _ in range(nrec):
            tag = self._u16()
            if tag != self.class_id:
                raise ValueError(f"record tag {tag:#x} at {self.p - 2:#x}")
            key = self._str()
            vals = []
            for name, t in self.fields:
                flag = self.d[self._adv(1)]
                if flag == 0x30:
                    vals.append(None)
                    continue
                if flag != 0x31:
                    raise ValueError(f"{key}.{name}: flag {flag:#x} at {self.p - 1:#x}")
                n = self._u16()
                vals.append([self._val(t) for _ in range(n)])
            self.records.append([key, vals])
        self.trailer = self.d[self.p:]

    def _adv(self, n):
        p = self.p
        self.p += n
        return p

    def _u16(self):
        return struct.unpack_from("<H", self.d, self._adv(2))[0]

    def _str(self):
        n, = struct.unpack_from("<I", self.d, self._adv(4))
        return self.d[self._adv(n):self.p].decode("latin-1")

    def _val(self, t):
        code, cnt = TYPES[t]
        if code == "str":
            return self._str()
        if code == "str2":
            return (self._str(), self._str())
        if code == "script":
            kind = self.d[self._adv(1)]
            if kind == 0:
                return (0, None, b"")
            if kind != 2:
                raise ValueError(f"script kind {kind} at {self.p - 1:#x}")
            unk, n = struct.unpack_from("<II", self.d, self._adv(8))
            return (kind, unk, self.d[self._adv(n):self.p])
        fmt = f"<{cnt}{code}" if cnt > 1 else f"<{code}"
        v = struct.unpack_from(fmt, self.d, self._adv(struct.calcsize(fmt)))
        return v if cnt > 1 else v[0]

    def field_index(self, name):
        return [f[0] for f in self.fields].index(name)

    def record(self, key):
        for r in self.records:
            if r[0] == key:
                return r
        raise KeyError(key)

    def edit(self, key, **fields):
        """Set fields of a record: a list sets all values, anything else one."""
        _, vals = self.record(key)
        for name, value in fields.items():
            vals[self.field_index(name)] = value if isinstance(value, list) else [value]

    def clone(self, src_key, new_key, **fields):
        """Copy a record under a new key (replacing one already there), then
        set fields on the copy."""
        _, vals = self.record(src_key)
        self.records = [r for r in self.records if r[0] != new_key]
        self.records.append([new_key, [list(v) if v is not None else None for v in vals]])
        self.edit(new_key, **fields)

    def values(self, field_type):
        """(values list, index) of every value of the given field type."""
        for _, vals in self.records:
            for (_, t), v in zip(self.fields, vals):
                if v is not None and t == field_type:
                    for i in range(len(v)):
                        yield v, i

    def serialize(self):
        out = bytearray()

        def s(x):
            b = x.encode("latin-1")
            out.extend(struct.pack("<I", len(b)) + b)

        out += struct.pack("<HHH", self.version, self.class_count, self.class_id)
        s(self.class_name)
        out += struct.pack("<HH", self.unk, len(self.fields))
        for name, t in self.fields:
            s(name)
            out.append(t)
        out += struct.pack("<H", len(self.records))
        for key, vals in self.records:
            out += struct.pack("<H", self.class_id)
            s(key)
            for (name, t), v in zip(self.fields, vals):
                if v is None:
                    out.append(0x30)
                    continue
                out.append(0x31)
                out += struct.pack("<H", len(v))
                code, cnt = TYPES[t]
                for e in v:
                    if code == "str":
                        s(e)
                    elif code == "str2":
                        s(e[0])
                        s(e[1])
                    elif code == "script":
                        out.append(e[0])
                        if e[0]:
                            out += struct.pack("<II", e[1], len(e[2])) + e[2]
                    elif cnt > 1:
                        out += struct.pack(f"<{cnt}{code}", *e)
                    else:
                        out += struct.pack(f"<{code}", e)
        out += self.trailer
        return bytes(out)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python wbr.py <file.wbr> [key filter]")
    with open(sys.argv[1], "rb") as f:
        w = Wbr(f.read())
    print(f"class {w.class_name} fields={[(n, hex(t)) for n, t in w.fields]}")
    print(f"{len(w.records)} records, trailer {len(w.trailer)} bytes {w.trailer[:16]!r}")
    flt = sys.argv[2] if len(sys.argv) > 2 else None
    for key, vals in w.records:
        if flt and flt not in key:
            continue
        print(f"[{key}]")
        for (name, _), v in zip(w.fields, vals):
            if v is not None:
                print(f"   {name} = {v}")
