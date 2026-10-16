"""Read/write the game's 'tongas_pack_v30000' data.pak.

Layout: magic(18) u32 count, u32 table_bytes, then count x
(u32 offset, u32 size, u32 flags, u32 name_len, name); file data starts at
the next 32 KiB boundary, entries are stored back to back, and the file is
padded to a 32 KiB multiple. flags=1 entries are LZMA-alone streams
(5-byte props + u64 uncompressed size + data).
"""
import lzma
import struct

MAGIC = b"tongas_pack_v30000"
ALIGN = 0x8000
LZMA_PROPS = bytes([0x5D, 0x00, 0x00, 0x80, 0x00])  # lc3 lp0 pb2, 8 MiB dict


def parse(d):
    """[name, flags, stored bytes] for every entry of a pak's bytes."""
    if d[:18] != MAGIC:
        raise ValueError("not a tongas pack")
    count, = struct.unpack_from("<I", d, 18)
    p, entries = 26, []
    for _ in range(count):
        off, size, flags, n = struct.unpack_from("<IIII", d, p)
        name = d[p + 16:p + 16 + n].decode("latin-1")
        entries.append([name, flags, d[off:off + size]])
        p += 16 + n
    return entries


def read(path):
    with open(path, "rb") as f:
        return parse(f.read())


class Pak:
    """A pak's entries by name, decompressed on access."""

    def __init__(self, data):
        self.entries = parse(data)
        self.index = {name: i for i, (name, _, _) in enumerate(self.entries)}

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def get(self, name):
        _, flags, blob = self.entries[self.index[name]]
        return decompress(blob) if flags == 1 else blob

    def put(self, name, data):
        blob = compress(data)
        if name in self.index:
            self.entries[self.index[name]] = [name, 1, blob]
        else:
            self.index[name] = len(self.entries)
            self.entries.append([name, 1, blob])

    def save(self, path):
        write(path, self.entries)


def decompress(blob):
    return lzma.decompress(blob, format=lzma.FORMAT_ALONE)


def _lzma_literals(data):
    """Encode data as an LZMA1 stream (lc3 lp0 pb2) using only literals.

    liblzma's raw encoder always appends an end-of-payload marker, which the
    known-size .lzma header used by this game does not allow. Literal-only
    coding keeps the stream marker-free; files compress less but stay valid.
    """
    out = bytearray()
    low, rng, cache, cache_size = 0, 0xFFFFFFFF, 0, 1

    def shift_low():
        nonlocal low, cache, cache_size
        if low < 0xFF000000 or low >= 1 << 32:
            carry = low >> 32
            temp = cache
            while True:
                out.append((temp + carry) & 0xFF)
                temp = 0xFF
                cache_size -= 1
                if cache_size == 0:
                    break
            cache = (low >> 24) & 0xFF
        cache_size += 1
        low = (low & 0x00FFFFFF) << 8

    is_match = [1024] * 4          # state is always 0 with literals only
    literal = [1024] * (0x300 * 8)
    prev = 0
    for pos, byte in enumerate(data):
        probs = (is_match, pos & 3)
        for prob_list, idx, bit in [(probs[0], probs[1], 0)] + [
                (literal, (prev >> 5) * 0x300 + ((byte | 0x100) >> (8 - i)), (byte >> (7 - i)) & 1)
                for i in range(8)]:
            p = prob_list[idx]
            bound = (rng >> 11) * p
            if bit == 0:
                rng = bound
                prob_list[idx] = p + ((2048 - p) >> 5)
            else:
                low += bound
                rng -= bound
                prob_list[idx] = p - (p >> 5)
            while rng < 1 << 24:
                rng = (rng << 8) & 0xFFFFFFFF
                shift_low()
        prev = byte
    for _ in range(5):
        shift_low()
    return bytes(out)


def compress(data):
    blob = LZMA_PROPS + struct.pack("<Q", len(data)) + _lzma_literals(data)
    if decompress(blob) != data:
        raise RuntimeError("LZMA round-trip failed")
    return blob


def write(path, entries):
    table = bytearray()
    names = [e[0].encode("latin-1") for e in entries]
    table_bytes = sum(16 + len(n) for n in names)
    off = (len(MAGIC) + 8 + table_bytes + ALIGN - 1) & ~(ALIGN - 1)
    for (name, flags, blob), n in zip(entries, names):
        table += struct.pack("<IIII", off, len(blob), flags, len(n)) + n
        off += len(blob)
    out = bytearray(MAGIC + struct.pack("<II", len(entries), table_bytes) + table)
    out += bytes(((len(out) + ALIGN - 1) & ~(ALIGN - 1)) - len(out))
    for _, _, blob in entries:
        out += blob
    out += bytes(((len(out) + ALIGN - 1) & ~(ALIGN - 1)) - len(out))
    with open(path, "wb") as f:
        f.write(out)
