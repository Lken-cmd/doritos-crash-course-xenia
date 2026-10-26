"""Patch the templates' Lua 5.1 chunks (little-endian, 4-byte int/size_t/instruction,
8-byte number)."""
import struct

# The opcodes the mod uses.
OP = {"MOVE": 0, "LOADK": 1, "LOADBOOL": 2, "GETUPVAL": 4, "GETGLOBAL": 5, "GETTABLE": 6,
      "SETTABLE": 9, "NEWTABLE": 10, "SELF": 11, "ADD": 12, "LEN": 20, "JMP": 22, "TEST": 26,
      "CALL": 28, "RETURN": 30, "SETLIST": 34}


class _Reader:
    def __init__(self, data):
        if data[:5] != b"\x1bLua\x51" or data[6:11] != b"\x01\x04\x04\x04\x08":
            raise ValueError(f"unsupported Lua chunk header {data[:12].hex()}")
        self.d = data
        self.p = 12
        self.layout = []  # per function: (constant count offset, end of constants)
        self.header = []  # per function: (max stack size offset, line info count offset)

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
        stack_at = self.p - 1
        n = self.int()
        code_at = self.p
        self.p += 4 * n
        consts = []
        consts_at = self.p
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
        self.layout.append((consts_at, self.p))
        header = len(self.header)
        self.header.append(None)
        for _ in range(self.int()):
            self.function(out)
        self.header[header] = (stack_at, self.p)
        n = self.int()                      # line info
        self.p += 4 * n
        for _ in range(self.int()):         # locals
            self.string()
            self.p += 8
        for _ in range(self.int()):         # upvalue names
            self.string()


def functions(chunk):
    """(code offset, instruction count, constants) per function; chunks end with 1 extra byte."""
    out = []
    r = _Reader(chunk)
    r.function(out)
    if r.p != len(chunk) - 1:
        raise ValueError(f"parsed {r.p} of {len(chunk)} bytes")
    return out


def abc(op, a, b, c):
    if not (0 <= op < 64 and 0 <= a < 256 and 0 <= b < 512 and 0 <= c < 512):
        raise ValueError(f"operand out of range: abc({op}, {a}, {b}, {c})")
    return op | a << 6 | c << 14 | b << 23


def abx(op, a, bx):
    if not (0 <= op < 64 and 0 <= a < 256 and 0 <= bx < 1 << 18):
        raise ValueError(f"operand out of range: abx({op}, {a}, {bx})")
    return op | a << 6 | bx << 14


RK = 256  # RK(c) operand for constant c
SBX = 131071  # sBx bias: abx(JMP, 0, SBX + offset)


def instructions(chunk, func):
    """Instructions of function `func` (walk order, 0 = main chunk)."""
    code_at, n, _ = functions(chunk)[func]
    return list(struct.unpack_from(f"<{n}I", chunk, code_at))


def jump_target(pc, ins):
    """Target of a JMP at `pc`, else None."""
    if ins & 0x3F != OP["JMP"]:
        return None
    return pc + 1 + (ins >> 14) - SBX


def add_string_constant(chunk, func, s):
    """Add string constant `s` to function `func`. Returns (chunk, constant index)."""
    r = _Reader(chunk)
    funcs = []
    r.function(funcs)
    _, _, consts = funcs[func]
    if s.encode() in consts:
        return chunk, consts.index(s.encode())
    count_at, end = r.layout[func]
    entry = b"\x04" + struct.pack("<I", len(s) + 1) + s.encode() + b"\0"
    data = (chunk[:count_at] + struct.pack("<I", len(consts) + 1) + chunk[count_at + 4:end]
            + entry + chunk[end:])
    return data, len(consts)


def set_code(chunk, func, pc, instructions):
    """Overwrite instructions of function `func` from `pc` on."""
    code_at, n, _ = functions(chunk)[func]
    if pc + len(instructions) > n:
        raise ValueError("past the end of the function")
    data = bytearray(chunk)
    for i, ins in enumerate(instructions):
        struct.pack_into("<I", data, code_at + 4 * (pc + i), ins)
    return bytes(data)


def prepend_code(chunk, func, instructions, stack):
    """Insert instructions at the start of function `func`. They use R0..R(stack-1), so it
    must take no parameters. Line info (if any) is extended, as Lua checks its size."""
    r = _Reader(chunk)
    funcs = []
    r.function(funcs)
    code_at, n, _ = funcs[func]
    stack_at, lines_at = r.header[func]
    if chunk[stack_at - 2]:  # header bytes: upvalues, parameters, vararg flag, max stack
        raise ValueError(f"function {func} takes parameters; R0.. are not free")
    nlines, = struct.unpack_from("<I", chunk, lines_at)
    new = b"".join(struct.pack("<I", i) for i in instructions)
    data = bytearray(chunk)
    if nlines:
        if nlines != n:
            raise ValueError("line info does not match the code")
        first = data[lines_at + 4:lines_at + 8]
        data[lines_at:lines_at + 4] = struct.pack("<I", nlines + len(instructions))
        data[lines_at + 4:lines_at + 4] = first * len(instructions)
    data[code_at:code_at] = new
    data[code_at - 4:code_at] = struct.pack("<I", n + len(instructions))
    data[stack_at] = max(data[stack_at], stack)
    return bytes(data)


def read_global_as_false(chunk, name):
    """Replace every read of global `name` with false. Returns (chunk, reads changed)."""
    data = bytearray(chunk)
    changed = 0
    for code_at, n, consts in functions(chunk):
        for pc in range(n):
            at = code_at + 4 * pc
            ins, = struct.unpack_from("<I", data, at)
            if ins & 0x3F == OP["GETGLOBAL"] and consts[ins >> 14] == name:
                a = (ins >> 6) & 0xFF
                struct.pack_into("<I", data, at, OP["LOADBOOL"] | a << 6)   # LOADBOOL A 0 0
                changed += 1
    return bytes(data), changed
