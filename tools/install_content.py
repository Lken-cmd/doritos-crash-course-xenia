"""Install an Xbox 360 STFS package (DLC, title update) into Xenia Canary's
content folder, as File > Install Content does.

usage: python install_content.py <package or .zip> <xenia_dir> [--override-dir <dir>]

  <content>/<profile id>/<title id>/<content type>/<package name>/<files>
  <content>/<profile id>/<title id>/Headers/<content type>/<package name>.header

--override-dir: files copied over the installed ones (the modded patch.pak).
The .header is XCONTENT_AGGREGATE_DATA (0x148 bytes), the only format Canary
02d2cb5 reads; newer builds accept it as their old format.
"""
import argparse
import os
import struct

import stfs

AGGREGATE_DATA_SIZE = 0x148     # sizeof(XCONTENT_AGGREGATE_DATA) in xenia
MAX_NAME = 42                   # its ASCII file name field


def aggregate_data(content_type, display, file_name, xuid, title_id):
    """xenia's XCONTENT_AGGREGATE_DATA, big-endian like guest memory."""
    out = bytearray(AGGREGATE_DATA_SIZE)
    struct.pack_into(">II", out, 0x0, 1, content_type)  # device 1 = HDD
    name = display.encode("utf-16-be")[:0xFE]
    out[0x8:0x8 + len(name)] = name
    fn = file_name.encode("ascii")[:MAX_NAME]
    out[0x108:0x108 + len(fn)] = fn
    struct.pack_into(">QI", out, 0x138, xuid, title_id)
    return bytes(out)


def install(src, xenia_dir, override=None):
    """Install a package, or the (largest) package inside a .zip."""
    with stfs.extracted(src) as path:
        _install(path, xenia_dir, override)


def package_name(file_name, title_id, content_type, media_id):
    """The installed folder's name: the file name if it fits the header's
    42-byte ASCII field (Xenia finds the folder through it), else one from the
    header."""
    if file_name.isascii() and len(file_name) <= MAX_NAME:
        return file_name
    return f"{title_id:08X}_{content_type:08X}_{media_id:08X}"


def warn_other_updates(type_dir, keep):
    """Point out other installed title updates of the game (Xenia uses only
    one). They are left alone."""
    if not os.path.isdir(type_dir):
        return
    for other in sorted(os.listdir(type_dir)):
        if other != keep and os.path.isdir(os.path.join(type_dir, other)):
            print(f"  Note: another title update of this game is installed too: "
                  f"{os.path.join(type_dir, other)}. Xenia might use it instead of this one; "
                  f"if the mod doesn't work, delete that folder.")


def _install(src, xenia_dir, override):
    with open(src, "rb") as f:
        info = stfs.header_info(f.read(stfs.HEADER_PEEK))
    if info is None:
        raise ValueError(f"{src} is not an Xbox 360 package")
    content_type, title_id, profile_id, display, media_id = info
    name = package_name(os.path.basename(src), title_id, content_type, media_id)

    root = os.path.join(xenia_dir, "content", f"{profile_id:016X}", f"{title_id:08X}")
    type_dir = os.path.join(root, f"{content_type:08X}")
    data_dir = os.path.join(type_dir, name)
    header_path = os.path.join(root, "Headers", f"{content_type:08X}", name + ".header")
    if content_type == stfs.TITLE_UPDATE:
        warn_other_updates(type_dir, name)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.dirname(header_path), exist_ok=True)

    with stfs.Stfs(src) as pkg:
        installed = set(pkg.extract_all(data_dir))
    with open(header_path, "wb") as f:
        f.write(aggregate_data(content_type, display, name, profile_id, title_id))
    print(f"installed '{display}' (title {title_id:08X}, type {content_type:08X}) -> {data_dir}")

    if override:
        for fn in sorted(os.listdir(override)):
            if fn not in installed:
                continue
            with open(os.path.join(override, fn), "rb") as fi, \
                    open(os.path.join(data_dir, fn), "wb") as fo:
                fo.write(fi.read())
            print(f"  replaced {fn} from {override}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Install an Xbox 360 package into Xenia Canary.")
    ap.add_argument("package", help="the package, or a .zip containing it")
    ap.add_argument("xenia_dir", help="Xenia's folder with content/ (portable) or Documents\\Xenia")
    ap.add_argument("--override-dir", help="copy these files over the installed ones")
    a = ap.parse_args()
    install(a.package, a.xenia_dir, a.override_dir)
