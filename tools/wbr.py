"""Reader/writer for the engine's binary templates (*.wbr, little-endian).

  u16 version(2), u16 class_count(1)
  u16 class_id, str class_name, u16 unk(1), u16 field_count
  field_count x (str name, u8 type)
  u16 record_count
  record_count x (u16 class_id, str key,
                  field_count x ('1' u16 n, n x value | '0'))
  trailing bytes kept verbatim
str = u32 length + bytes (no terminator); text = u32 length + UTF-16LE.
The two games number the field types differently (TYPES, TYPES_CC2).
"""
import struct

# value codes: a struct format character, or one of
#   str    u32 length + latin-1 bytes (names, resource refs)
#   text   u32 character count + UTF-16LE (localized text)
#   str2   two strs (texture: name + file)
#   istr   u32 + str (icon: index + sheet)
#   curve  u32 count + count x (f32 x, f32 y, u8 interpolation)
#   script u8 kind; 0: empty, 1: u32 + str (named function),
#          2: u32 + u32 length + Lua 5.1 bytecode
# type number -> (code, element count)
TYPES = {  # Doritos Crash Course
    0x00: ("i", 1),      # int
    0x01: ("i", 1),      # enum
    0x02: ("B", 1),      # bool
    0x03: ("f", 1),      # float
    0x04: ("text", 1),   # localized text
    0x06: ("str", 1),    # string / resource ref
    0x08: ("f", 2),      # vec2
    0x09: ("f", 3),      # vec3
    0x0A: ("f", 4),      # vec4
    0x0B: ("f", 3),      # angles
    0x0C: ("3s", 1),     # RGB colour
    0x0D: ("str2", 1),   # texture ref
    0x0E: ("script", 1),
}
TYPES_CC2 = {  # Doritos Crash Course 2: one higher from 2 on, plus new types
    0x00: ("i", 1),
    0x01: ("i", 1),
    0x02: ("i", 1),      # event id
    **{t + 1: v for t, v in TYPES.items() if t >= 2 and t != 0x0D},
    0x0E: ("istr", 1),   # icon ref
    0x14: ("curve", 1),
}


def _put_str(out, s):
    b = s.encode("latin-1")
    out += struct.pack("<I", len(b)) + b


def _put_text(out, s):
    out += struct.pack("<I", len(s)) + s.encode("utf-16-le")


def _put_str2(out, e):
    _put_str(out, e[0])
    _put_str(out, e[1])


def _put_istr(out, e):
    out += struct.pack("<I", e[0])
    _put_str(out, e[1])


def _put_curve(out, e):
    out += struct.pack("<I", len(e))
    for key_point in e:
        out += struct.pack("<ffB", *key_point)


def _put_script(out, e):
    out.append(e[0])
    if e[0] == 1:
        out += struct.pack("<I", e[1])
        _put_str(out, e[2])
    elif e[0] == 2:
        out += struct.pack("<II", e[1], len(e[2])) + e[2]


# value code -> (Wbr reader method, writer); any other code is a struct format
CODECS = {"str": ("_str", _put_str), "text": ("_text", _put_text),
          "str2": ("_str2", _put_str2), "istr": ("_istr", _put_istr),
          "curve": ("_curve", _put_curve), "script": ("_script", _put_script)}


class Wbr:
    def __init__(self, data, types=TYPES):
        self.types = types
        self.d = data
        self.p = 0
        self.version, self.class_count = self._u16(), self._u16()
        self.class_id = self._u16()
        self.class_name = self._str()
        self.unk = self._u16()
        nfields = self._u16()
        self.fields = [(self._str(), self.d[self._adv(1)]) for _ in range(nfields)]
        for name, t in self.fields:
            if t not in types:
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

    def _u32(self):
        return struct.unpack_from("<I", self.d, self._adv(4))[0]

    def _str(self):
        n = self._u32()
        return self.d[self._adv(n):self.p].decode("latin-1")

    def _val(self, t):
        code, cnt = self.types[t]
        if code in CODECS:
            return getattr(self, CODECS[code][0])()
        fmt = f"<{cnt}{code}" if cnt > 1 else f"<{code}"
        v = struct.unpack_from(fmt, self.d, self._adv(struct.calcsize(fmt)))
        return v if cnt > 1 else v[0]

    def _text(self):
        n = self._u32()
        return self.d[self._adv(2 * n):self.p].decode("utf-16-le")

    def _str2(self):
        return (self._str(), self._str())

    def _istr(self):
        return (self._u32(), self._str())

    def _curve(self):
        n = self._u32()
        return [struct.unpack_from("<ffB", self.d, self._adv(9)) for _ in range(n)]

    def _script(self):
        kind = self.d[self._adv(1)]
        if kind == 0:
            return (0, None, b"")
        if kind == 1:
            return (1, self._u32(), self._str())
        if kind != 2:
            raise ValueError(f"script kind {kind} at {self.p - 1:#x}")
        unk, n = self._u32(), self._u32()
        return (kind, unk, self.d[self._adv(n):self.p])

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
        """Copy a record to `new_key` (replacing it), then set fields on the copy."""
        _, vals = self.record(src_key)
        self.records = [r for r in self.records if r[0] != new_key]
        self.records.append([new_key, [list(v) if v is not None else None for v in vals]])
        self.edit(new_key, **fields)

    def values(self, code):
        """(values list, index) of every value of a code ("str", "script", ...)."""
        for _, vals in self.records:
            for (_, t), v in zip(self.fields, vals):
                if v is not None and self.types[t][0] == code:
                    for i in range(len(v)):
                        yield v, i

    def serialize(self):
        out = bytearray()
        out += struct.pack("<HHH", self.version, self.class_count, self.class_id)
        _put_str(out, self.class_name)
        out += struct.pack("<HH", self.unk, len(self.fields))
        for name, t in self.fields:
            _put_str(out, name)
            out.append(t)
        out += struct.pack("<H", len(self.records))
        for key, vals in self.records:
            out += struct.pack("<H", self.class_id)
            _put_str(out, key)
            for (name, t), v in zip(self.fields, vals):
                if v is None:
                    out.append(0x30)
                    continue
                out.append(0x31)
                out += struct.pack("<H", len(v))
                code, cnt = self.types[t]
                for e in v:
                    if code in CODECS:
                        CODECS[code][1](out, e)
                    elif cnt > 1:
                        out += struct.pack(f"<{cnt}{code}", *e)
                    else:
                        out += struct.pack(f"<{code}", e)
        out += self.trailer
        return bytes(out)

    def serialize_checked(self, name):
        """serialize(), checked to re-parse to the same bytes."""
        data = self.serialize()
        if Wbr(data, self.types).serialize() != data:
            raise RuntimeError(f"{name} does not re-parse")
        return data


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python wbr.py <file.wbr> [key filter] [--cc2]")
    with open(sys.argv[1], "rb") as f:
        w = Wbr(f.read(), TYPES_CC2 if "--cc2" in sys.argv else TYPES)
    print(f"class {w.class_name} fields={[(n, hex(t)) for n, t in w.fields]}")
    print(f"{len(w.records)} records, trailer {len(w.trailer)} bytes {w.trailer[:16]!r}")
    flt = next((a for a in sys.argv[2:] if a != "--cc2"), None)
    for key, vals in w.records:
        if flt and flt not in key:
            continue
        print(f"[{key}]")
        for (name, _), v in zip(w.fields, vals):
            if v is not None:
                print(f"   {name} = {v}")
