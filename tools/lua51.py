"""Just enough of the Lua 5.1 bytecode format to patch instructions in place.

The game's templates embed compiled Lua 5.1 chunks (little-endian, 4-byte
int/size_t/instruction, 8-byte number) for menu actions and scripts.
"""
import struct

GETGLOBAL, LOADBOOL = 5, 2


class _Reader:
    def __init__(self, data):
        if data[:5] != b"\x1bLua\x51" or data[6:11] != b"\x01\x04\x04\x04\x08":
            raise ValueError(f"unsupported Lua chunk header {data[:12].hex()}")
        self.d = data
        self.p = 12

    def int(self):
        v, = struct.unpack_from("<I", self.d, self.p)
        self.p += 4
        return v

    def string(self):
        n = self.int()
        self.p += n
        return self.d[self.p - n:self.p - 1] if n else None

    def function(self, out):
        self.string()                       # source name
        self.p += 4 + 4 + 4                 # line defined, last line, nups/params/vararg/stack
        n = self.int()
        code_at = self.p
        self.p += 4 * n
        consts = []
        for _ in range(self.int()):
            t = self.d[self.p]
            self.p += 1
            if t == 1:
                consts.append(bool(self.d[self.p]))
                self.p += 1
            elif t == 3:
                consts.append(struct.unpack_from("<d", self.d, self.p)[0])
                self.p += 8
            elif t == 4:
                consts.append(self.string())
            else:
                consts.append(None)
        out.append((code_at, n, consts))
        for _ in range(self.int()):
            self.function(out)
        n = self.int()                      # line info
        self.p += 4 * n
        for _ in range(self.int()):         # locals
            self.string()
            self.p += 8
        for _ in range(self.int()):         # upvalue names
            self.string()


def functions(chunk):
    """(code offset, instruction count, constants) of every function.

    The templates store each chunk with one trailing byte."""
    out = []
    r = _Reader(chunk)
    r.function(out)
    if r.p != len(chunk) - 1:
        raise ValueError(f"parsed {r.p} of {len(chunk)} bytes")
    return out


def read_global_as_false(chunk, name):
    """Replace every read of global `name` with the constant false.

    Returns (new chunk, number of instructions changed)."""
    data = bytearray(chunk)
    changed = 0
    for code_at, n, consts in functions(chunk):
        for pc in range(n):
            at = code_at + 4 * pc
            ins, = struct.unpack_from("<I", data, at)
            if ins & 0x3F == GETGLOBAL and consts[ins >> 14] == name:
                a = (ins >> 6) & 0xFF
                struct.pack_into("<I", data, at, LOADBOOL | a << 6)   # LOADBOOL A 0 0
                changed += 1
    return bytes(data), changed
