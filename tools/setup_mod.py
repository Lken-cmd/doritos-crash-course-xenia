"""One-step setup: build the mod and install it into Xenia Canary.

usage: python setup_mod.py [--xenia <folder>] [--build <dir>] [<file or folder> ...]

Give it the game, Title Update 2 and the City Lights DLC (packages or .zip
files, in any order, or folders that contain them); without arguments it
asks. It tells the packages apart by their headers, builds the mod
(build_mod.py), installs the update and the DLC into Xenia's content folder
(install_content.py), switches Xenia to the full game instead of the trial,
and saves Xenia's location for "Play Doritos Crash Course.bat".
"""
import argparse
import contextlib
import os
import re
import shlex
import sys

import build_mod
import install_content
import stfs

TITLE_ID = 0x58410A71
GAME, UPDATE, DLC = 0x000D0000, 0x000B0000, 0x00000002
NAMES = {GAME: "game", UPDATE: "title update", DLC: "City Lights DLC"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def documents_dir():
    """The user's Documents folder as Xenia finds it (it may have been moved,
    e.g. to OneDrive)."""
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


def for_batch(path):
    """`path` as bytes that `set /p` in a .bat reads back whatever the
    console's code page: plain ASCII, or else the 8.3 short path (which is
    ASCII where the file system keeps short names)."""
    if path.isascii() or os.name != "nt":
        return path.encode()
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) and buf.value.isascii():
        return buf.value.encode()
    return path.encode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", "replace")


def find_packages(paths):
    """{content type: (file, zip member or None)} of this game's packages."""
    found = {}

    def check(p):
        try:
            pkgs = stfs.packages(p)
        except OSError:
            return
        for member, (ctype, title, _, _) in pkgs:
            if title == TITLE_ID and ctype in NAMES and ctype not in found:
                found[ctype] = (p, member)
                print(f"  {NAMES[ctype]}: {p}" + (f" ({member})" if member else ""))

    for p in paths:
        if os.path.isdir(p):
            for top, dirs, files in os.walk(p):
                if top[len(p):].count(os.sep) >= 2:
                    dirs[:] = []
                for fn in files:
                    check(os.path.join(top, fn))
        elif os.path.isfile(p):
            check(p)
        else:
            print(f"  not found: {p}")
    return found


def ask_paths(prompt):
    line = input(prompt).strip()
    return [s.strip('"') for s in shlex.split(line, posix=False)]


def xenia_folder(given):
    folder = given
    default = os.path.join(documents_dir(), "Xenia Canary")
    while True:
        if folder is None and os.path.isfile(os.path.join(default, "xenia_canary.exe")):
            folder = default
        if folder and os.path.isfile(os.path.join(folder, "xenia_canary.exe")):
            return os.path.abspath(folder)
        if folder:
            print(f"  no xenia_canary.exe in {folder}")
        folder = (ask_paths("Drag your Xenia Canary folder (with xenia_canary.exe) here "
                            "and press Enter: ") or [""])[0]


def enable_full_game(config):
    """Set license_mask = 1 in Xenia's config; False if there is no config."""
    if not os.path.isfile(config):
        return False
    with open(config, encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(r"(?m)^(license_mask\s*=\s*)-?\d+", r"\g<1>1", text)
    if not n:
        return False
    with open(config, "w", encoding="utf-8") as f:
        f.write(new)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="game, update and DLC files, or folders with them")
    ap.add_argument("--xenia", help="Xenia Canary folder (default: Documents\\Xenia Canary)")
    ap.add_argument("--build", default=os.path.join(ROOT, "build"), help="output folder")
    args = ap.parse_args()

    paths = args.paths or ask_paths(
        "Drag the folder with your game files (or the files themselves) here and press Enter: ")
    print("Looking for the game files:")
    found = find_packages(paths)
    if GAME not in found:
        sys.exit("The game package (Doritos Crash Course, XBLA) was not found.")
    if DLC in found and UPDATE not in found:
        print("The City Lights DLC needs the title update, which was not found; "
              "skipping the DLC.")
        del found[DLC]

    xenia = xenia_folder(args.xenia)
    portable = os.path.isfile(os.path.join(xenia, "portable.txt"))
    user_dir = xenia if portable else os.path.join(documents_dir(), "Xenia")

    with contextlib.ExitStack() as stack:
        pkgs = {ctype: stack.enter_context(stfs.extracted(path, member))
                for ctype, (path, member) in found.items()}

        print("\nBuilding the mod (takes about a minute):")
        build_mod.main(pkgs[GAME], args.build, pkgs.get(UPDATE))

        print("\nInstalling into Xenia:")
        if UPDATE in pkgs:
            install_content.install(pkgs[UPDATE], user_dir, os.path.join(args.build, "update"))
        if DLC in pkgs:
            install_content.install(pkgs[DLC], user_dir)

    config = os.path.join(user_dir, "xenia-canary.config.toml")
    full = enable_full_game(config)
    with open(os.path.join(args.build, "xenia.txt"), "wb") as f:
        f.write(for_batch(os.path.join(xenia, "xenia_canary.exe")))

    print("\nDone. Start the game with \"Play Doritos Crash Course.bat\".")
    if not full:
        print(f"Xenia has no config yet ({config}). Start Xenia once, close it, and run "
              "this setup again, or set license_mask = 1 in that file yourself; "
              "otherwise the game runs as the trial version.")


if __name__ == "__main__":
    main()
