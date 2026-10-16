"""Minimal read-only STFS (LIVE/PIRS/CON) package reader."""
import contextlib
import struct
import tempfile
import zipfile

BLOCK = 0x1000
MAGICS = (b"LIVE", b"PIRS", b"CON ")
HEADER_PEEK = 0x500  # enough of the header for header_info()


def _i24le(b):
    return b[0] | (b[1] << 8) | (b[2] << 16)


def _i24be(b):
    return (b[0] << 16) | (b[1] << 8) | b[2]


def header_info(head):
    """(content type, title id, profile id, display name) from the start of
    a package, or None if it isn't an STFS package."""
    if head[:4] not in MAGICS or len(head) < 0x491:
        return None
    content_type, = struct.unpack_from(">I", head, 0x344)
    title_id, = struct.unpack_from(">I", head, 0x360)
    profile_id, = struct.unpack_from(">Q", head, 0x371)
    display = head[0x411:0x491].decode("utf-16-be", "replace").split("\0")[0]
    return content_type, title_id, profile_id, display


def packages(path):
    """[(zip member or None, header_info)] for a package file, or for each
    package inside a .zip, largest first."""
    if not zipfile.is_zipfile(path):
        with open(path, "rb") as f:
            info = header_info(f.read(HEADER_PEEK))
        return [(None, info)] if info else []
    found = []
    with zipfile.ZipFile(path) as z:
        for m in sorted(z.infolist(), key=lambda m: -m.file_size):
            with z.open(m) as f:
                info = header_info(f.read(HEADER_PEEK))
            if info:
                found.append((m.filename, info))
    return found


@contextlib.contextmanager
def extracted(path, member=None):
    """Path of a package on disk: the file itself, or a .zip's `member`
    (default: its largest package) extracted to a temporary folder."""
    if not zipfile.is_zipfile(path):
        yield path
        return
    if member is None:
        found = packages(path)
        if not found:
            raise ValueError(f"no Xbox 360 package in {path}")
        member = found[0][0]
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as z:
            out = z.extract(member, tmp)
        yield out


class Stfs:
    def __init__(self, path):
        self.f = open(path, "rb")
        try:
            self._parse_header(self.f.read(0x1000))
        except Exception:
            self.f.close()
            raise

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _parse_header(self, hdr):
        self.magic = hdr[:4]
        if self.magic not in MAGICS:
            raise ValueError("not an STFS package")
        header_size, = struct.unpack(">I", hdr[0x340:0x344])
        self.data_base = (header_size + 0xFFF) & ~0xFFF
        vd = hdr[0x379:0x379 + 0x24]
        self.ft_count, = struct.unpack("<H", vd[3:5])
        self.ft_block = _i24le(vd[5:8])
        # Same rule as xenia: 0xB000 header or read-only flag -> one copy of
        # each hash table for LIVE/PIRS, two for CON.
        if self.data_base == 0xB000 or (vd[2] & 1):
            self.shift = 1 if self.magic == b"CON " else 0
        else:
            self.shift = 0 if self.magic == b"CON " else 1

    def _data_block(self, n):
        s = self.shift
        r = (((n + 0xAA) // 0xAA) << s) + n
        if n < 0xAA:
            return r
        if n < 0x70E4:
            return r + (((n + 0x70E4) // 0x70E4) << s)
        return (1 << s) + r + (((n + 0x70E4) // 0x70E4) << s)

    def _l0_hash_block(self, n):
        if n < 0xAA:
            return 0
        step0 = 0xAB if self.shift == 0 else 0xAC
        num = (n // 0xAA) * step0 + (((n // 0x70E4) + 1) << self.shift)
        return num if n // 0x70E4 == 0 else num + (1 << self.shift)

    def _read_block(self, n):
        self.f.seek(self.data_base + self._data_block(n) * BLOCK)
        return self.f.read(BLOCK)

    def _next_block(self, n):
        self.f.seek(self.data_base + self._l0_hash_block(n) * BLOCK + (n % 0xAA) * 0x18)
        return _i24be(self.f.read(0x18)[0x15:0x18])

    def entries(self):
        out, n = [], self.ft_block
        for _ in range(self.ft_count):
            blk = self._read_block(n)
            for i in range(0, BLOCK, 0x40):
                e = blk[i:i + 0x40]
                flags = e[0x28]
                if not flags & 0x3F:
                    continue
                out.append({
                    "name": e[:flags & 0x3F].decode("latin-1"),
                    "dir": bool(flags & 0x80),
                    "contig": bool(flags & 0x40),
                    "blocks": _i24le(e[0x29:0x2C]),
                    "start": _i24le(e[0x2F:0x32]),
                    "parent": struct.unpack(">h", e[0x32:0x34])[0],
                    "size": struct.unpack(">I", e[0x34:0x38])[0],
                })
            n = self._next_block(n)
        for e in out:
            parts, p = [e["name"]], e["parent"]
            while p != -1:
                parts.append(out[p]["name"])
                p = out[p]["parent"]
            e["path"] = "/".join(reversed(parts))
        return out

    def read_file(self, e):
        data, n = bytearray(), e["start"]
        for _ in range(e["blocks"]):
            data += self._read_block(n)
            n = n + 1 if e["contig"] else self._next_block(n)
        return bytes(data[:e["size"]])

    def files(self):
        """{path: bytes} of every file in the package."""
        return {e["path"]: self.read_file(e) for e in self.entries() if not e["dir"]}
