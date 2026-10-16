"""Install an Xbox 360 STFS content package (e.g. DLC) into a Xenia Canary
content folder, laid out the way Xenia's File > Install Content does it.

usage: python install_content.py <package or .zip> <xenia_dir> [--override-dir <dir>]

  <content>/<profile id>/<title id>/<content type>/<package name>/<files>
  <content>/<profile id>/<title id>/Headers/<content type>/<package name>.header

--override-dir copies the files in <dir> over the installed ones afterwards
(used for the modded patch.pak of the title update).

The .header is written as XCONTENT_AGGREGATE_DATA (0x148 bytes). Xenia
Canary builds up to at least March 2026 (02d2cb5) only understand that
format and only list extracted folders; newer builds still accept it as
their "old header" format.
"""
import argparse
import os
import struct

import stfs

AGGREGATE_DATA_SIZE = 0x148     # sizeof(XCONTENT_AGGREGATE_DATA) in xenia


def aggregate_data(content_type, display, file_name, xuid, title_id):
    """xenia's XCONTENT_AGGREGATE_DATA, big-endian like guest memory."""
    out = bytearray(AGGREGATE_DATA_SIZE)
    struct.pack_into(">II", out, 0x0, 1, content_type)  # device 1 = HDD
    name = display.encode("utf-16-be")[:0xFE]
    out[0x8:0x8 + len(name)] = name
    fn = file_name.encode("ascii")[:42]
    out[0x108:0x108 + len(fn)] = fn
    struct.pack_into(">QI", out, 0x138, xuid, title_id)
    return bytes(out)


def install(src, xenia_dir, override=None, member=None):
    """Install a package, or a package inside a .zip (default: the largest)."""
    with stfs.extracted(src, member) as path:
        _install(path, xenia_dir, override)


def _install(src, xenia_dir, override):
    name = os.path.basename(src)
    with open(src, "rb") as f:
        info = stfs.header_info(f.read(stfs.HEADER_PEEK))
    if info is None:
        raise ValueError(f"{src} is not an Xbox 360 package")
    content_type, title_id, profile_id, display = info

    root = os.path.join(xenia_dir, "content", f"{profile_id:016X}", f"{title_id:08X}")
    data_dir = os.path.join(root, f"{content_type:08X}", name)
    header_path = os.path.join(root, "Headers", f"{content_type:08X}", name + ".header")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.dirname(header_path), exist_ok=True)

    with stfs.Stfs(src) as pkg:
        entries = pkg.entries()
        for e in entries:
            dst = os.path.join(data_dir, *e["path"].split("/"))
            if e["dir"]:
                os.makedirs(dst, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(pkg.read_file(e))
    with open(header_path, "wb") as f:
        f.write(aggregate_data(content_type, display, name, profile_id, title_id))
    print(f"installed '{display}' (title {title_id:08X}, type {content_type:08X}) -> {data_dir}")

    if override:
        installed = {e["path"] for e in entries if not e["dir"]}
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
