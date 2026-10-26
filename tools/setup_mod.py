"""One-step setup: build the mods and install them into Xenia Canary.

usage: python setup_mod.py [--xenia <folder>] [--build <dir>] [<file or folder> ...]

Inputs: the packages (CC1: game, Title Update 2, City Lights DLC; CC2: game,
Title Update 2) as files, .zip files or folders; asks if none are given.
Per game: build into <build>/cc1|cc2/, install the title update (and DLC)
into Xenia, copy the patch file. Then enable the full games and save Xenia's
path for the "Play ..." files. setup_gui.py is the window for the same steps.
"""
import argparse
import contextlib
import hashlib
import os
import re
import shlex
import shutil
import sys
import traceback
from typing import Callable, NamedTuple, Optional

import build_cc2
import build_mod
import install_content
import stfs

CC1, CC2 = 0x58410A71, 0x5841124F  # title ids
GAME, UPDATE, DLC = stfs.ARCADE_TITLE, stfs.TITLE_UPDATE, stfs.MARKETPLACE_CONTENT
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Game(NamedTuple):
    """What setup needs to know about one of the games."""
    title: int                      # title id
    name: str
    packages: dict                  # content type -> what that package is called
    update_media_id: int            # of Title Update 2 (all of a game's updates share it)
    update_sha1: str                # of Title Update 2's default.xexp
    without_update: Optional[str]   # note if the update is missing; None: it is required
    folder: str                     # build/<folder>/
    play: str                       # its "Play ..." file in the mod's folder
    patch: str                      # its Xenia patch file in patches/
    build: Callable                 # (packages by content type, build/<folder>, Xenia user dir)


class SetupError(Exception):
    """A problem the user can fix; the message says how."""


def documents_dir():
    """The Documents folder, also when moved (e.g. to OneDrive)."""
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
            return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


def for_batch(path):
    """`path` as bytes `set /p` in a .bat reads back in any code page: ASCII,
    else the 8.3 short path."""
    if path.isascii() or os.name != "nt":
        return path.encode()
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) and buf.value.isascii():
        return buf.value.encode()
    return path.encode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", "replace")


def find_packages(paths):
    """({(title id, content type): (file, zip member or None)}, [problems]).
    Folders are searched 5 levels deep (an Xbox 360 drive's
    Content\\<profile>\\<title>\\<type>\\<package>)."""
    found, problems = {}, []

    def check(p):
        if p.lower().endswith((".7z", ".rar")):
            problems.append(f"{p}: unpack this archive first (setup reads packages and .zip "
                            "files).")
            return
        try:
            pkgs = stfs.packages(p)
        except Exception as e:  # unreadable or unsupported zip, missing permissions, ...
            problems.append(f"{p}: could not be read ({e}). If it's an archive, unpack it first.")
            return
        for member, (ctype, title, _, _, media_id) in pkgs:
            key = (title, ctype)
            if key not in NAMES:
                continue
            if ctype == UPDATE and not is_update_2(GAMES[title], p, member, media_id):
                problems.append(f"{p}: this is a different title update; the mod needs "
                                f"{NAMES[key]} (media ID {GAMES[title].update_media_id:08X}).")
                continue
            if key not in found:
                found[key] = (p, member)
                print(f"  {NAMES[key]}: {p}" + (f" ({member})" if member else ""))

    for p in paths:
        if os.path.isdir(p):
            for top, dirs, files in os.walk(p):
                if top[len(p):].count(os.sep) >= 5:
                    dirs[:] = []
                for fn in files:
                    check(os.path.join(top, fn))
        elif os.path.isfile(p):
            check(p)
        else:
            problems.append(f"{p}: not found.")
    for problem in problems:
        print(f"  {problem}")
    return found, problems


def is_update_2(game, path, member, media_id):
    """Whether the title update package is Title Update 2 (the patches need it)."""
    if media_id != game.update_media_id:
        return False
    with stfs.extracted(path, member) as unpacked, stfs.Stfs(unpacked) as pkg:
        xexp = [e for e in pkg.entries() if e["path"] == "default.xexp"]
        return bool(xexp) and hashlib.sha1(pkg.read_file(xexp[0])).hexdigest() == game.update_sha1


def plan(found):
    """(games to set up, notes about what is missing or skipped)."""
    games, notes = [], []
    for game in GAMES.values():
        have = {ctype for title, ctype in found if title == game.title}
        if GAME not in have:
            if have:
                notes.append(f"{game.name}: the game package is missing; skipping it.")
        elif UPDATE in have or game.without_update:
            games.append(game)
            if UPDATE not in have:
                notes.append(game.without_update)
        else:
            notes.append(f"{game.name} needs its Title Update 2 (the mod's patches are made "
                         "for it); skipping it.")
    return games, notes


def ask_paths(prompt):
    line = input(prompt).strip()
    return [s.strip('"') for s in shlex.split(line, posix=False)]


def default_xenia():
    """Documents\\Xenia Canary if xenia_canary.exe is there, else None."""
    folder = os.path.join(documents_dir(), "Xenia Canary")
    return folder if is_xenia(folder) else None


def is_xenia(folder):
    return bool(folder) and os.path.isfile(os.path.join(folder, "xenia_canary.exe"))


def ask_xenia_folder(given):
    """The given or default Xenia folder, else ask until one has xenia_canary.exe."""
    folder = given or default_xenia()
    while not is_xenia(folder):
        if folder:
            print(f"  no xenia_canary.exe in {folder}")
        folder = (ask_paths("Drag your Xenia Canary folder (with xenia_canary.exe) here "
                            "and press Enter: ") or [""])[0]
    return os.path.abspath(folder)


def user_dir(xenia):
    """Xenia's config/content/patches folder: its own in portable mode
    (portable.txt), else Documents\\Xenia."""
    if os.path.isfile(os.path.join(xenia, "portable.txt")):
        return xenia
    return os.path.join(documents_dir(), "Xenia")


def config_path(xenia):
    return os.path.join(user_dir(xenia), "xenia-canary.config.toml")


def enable_full_game(config):
    """Set license_mask = 1 (full games, not trials). Returns None or a note
    for the user."""
    if not os.path.isfile(config):
        return (f"Xenia has no settings file yet ({config}). Start Xenia once, close it, and "
                "run this setup again; otherwise the games start as trial versions.")
    with open(config, encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(r"(?m)^(license_mask\s*=\s*)-?\d+", r"\g<1>1", text)
    if not n:
        return (f"There is no license_mask in {config}. Set license_mask = 1 there yourself; "
                "otherwise the games start as trial versions.")
    with open(config, "w", encoding="utf-8") as f:
        f.write(new)
    return None


def patch_switches(text):
    """{patch name: is_enabled} of a Xenia patch file."""
    out = {}
    for block in re.split(r"(?m)^\[\[patch\]\]$", text)[1:]:
        name = re.search(r'(?m)^\s*name = "([^"]*)"', block)
        on = re.search(r"(?m)^\s*is_enabled = (true|false)", block)
        if name and on:
            out[name.group(1)] = on.group(1) == "true"
    return out


def optional_patches(text):
    """Names of the user-switchable patches (desc starts with "Optional")."""
    return set(re.findall(r'(?m)^\s*name = "([^"]*)"\s*desc = "Optional', text))


def set_switches(text, switches):
    """`text` with the given patches switched on or off."""
    blocks = re.split(r"(?m)^(?=\[\[patch\]\]$)", text)
    for i, block in enumerate(blocks):
        name = re.search(r'(?m)^\s*name = "([^"]*)"', block)
        if block.startswith("[[patch]]") and name and name.group(1) in switches:
            on = "true" if switches[name.group(1)] else "false"
            blocks[i] = re.sub(r"(?m)^(\s*is_enabled = )(?:true|false)",
                               lambda m: m.group(1) + on, block, count=1)
    return "".join(blocks)


def install_patch(patch, user):
    """Copy patches/<patch> into Xenia's patches folder, keeping the optional
    patches' switches from an earlier copy."""
    patches = os.path.join(user, "patches")
    os.makedirs(patches, exist_ok=True)
    dst = os.path.join(patches, patch)
    with open(os.path.join(ROOT, "patches", patch), encoding="utf-8") as f:
        text = f.read()
    if os.path.isfile(dst):
        with open(dst, encoding="utf-8") as f:
            old = patch_switches(f.read())
        keep = optional_patches(text)
        text = set_switches(text, {k: v for k, v in old.items() if k in keep})
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  patch: {dst}")


def build_cc1_game(pkgs, out, user):
    print("\nBuilding the Doritos Crash Course mod (takes about a minute):")
    build_mod.main(pkgs[GAME], out, pkgs.get(UPDATE))
    print("\nInstalling Doritos Crash Course into Xenia:")
    if UPDATE in pkgs:
        install_content.install(pkgs[UPDATE], user, os.path.join(out, "update"))
        if DLC in pkgs:
            install_content.install(pkgs[DLC], user)
    install_patch(GAMES[CC1].patch, user)


def build_cc2_game(pkgs, out, user):
    print("\nBuilding the Doritos Crash Course 2 mod (takes about a minute):")
    game = os.path.join(out, "game")
    if os.path.isdir(game):
        shutil.rmtree(game)
    with stfs.Stfs(pkgs[GAME]) as pkg:
        n = len(pkg.extract_all(game))
    print(f"  unpacked the game: {n} files")
    data_pak = os.path.join(game, "data.pak")
    build_cc2.main(data_pak, data_pak, os.path.join(out, "preview"))
    print("\nInstalling Doritos Crash Course 2 into Xenia:")
    install_content.install(pkgs[UPDATE], user)
    install_patch(GAMES[CC2].patch, user)


GAMES = {g.title: g for g in [
    Game(CC1, "Doritos Crash Course",
         {GAME: "Doritos Crash Course", UPDATE: "Doritos Crash Course Title Update 2",
          DLC: "Doritos Crash Course City Lights DLC"},
         0x261A2859, "ce5f6fa5f9d8916f04812ec5f36546f294c4d50a",
         "Doritos Crash Course: no Title Update 2, so no City Lights DLC and no shirt colour "
         "fix.",
         "cc1", "Play Doritos Crash Course.bat", "58410A71 - Doritos Crash Course.patch.toml",
         build_cc1_game),
    Game(CC2, "Doritos Crash Course 2",
         {GAME: "Doritos Crash Course 2", UPDATE: "Doritos Crash Course 2 Title Update 2"},
         0x6FBC14D5, "8c074b1442d533bcff40ab97682b8e8218e87891", None,
         "cc2", "Play Doritos Crash Course 2.bat",
         "5841124F - Doritos Crash Course 2 (offline).patch.toml",
         build_cc2_game),
]}
# (title id, content type) -> what that package is called
NAMES = {(g.title, ctype): name for g in GAMES.values() for ctype, name in g.packages.items()}


def remove_old_layout(build):
    """Remove the old CC1 layout (build/game, build/update, build/preview)."""
    if not os.path.isfile(os.path.join(build, "game", "default.xex")):
        return
    for folder in ("game", "update", "preview"):
        if os.path.isdir(os.path.join(build, folder)):
            shutil.rmtree(os.path.join(build, folder))
    print(f"Removed the old build folders game, update and preview in {build} "
          "(Crash Course 1 is now built into cc1).")


def run(found, xenia, build):
    """Set up each game `plan` allows, independently. Returns (games done,
    [(game, why it failed)], None or a note about the full games)."""
    games, notes = plan(found)
    for note in notes:
        print(note)
    if not games:
        raise SetupError("Neither Doritos Crash Course nor Doritos Crash Course 2 was found "
                         "among your files (see above for what is missing).")
    user = user_dir(xenia)
    remove_old_layout(build)
    done, failed = [], []
    for game in games:
        try:
            with contextlib.ExitStack() as stack:
                pkgs = {ctype: stack.enter_context(stfs.extracted(path, member))
                        for (title, ctype), (path, member) in found.items()
                        if title == game.title}
                # stale previews of older builds
                shutil.rmtree(os.path.join(build, game.folder, "preview"), ignore_errors=True)
                game.build(pkgs, os.path.join(build, game.folder), user)
            done.append(game)
        except PermissionError as e:
            failed.append((game, f"A file is in use ({e.filename}). Close Xenia, and anything "
                                 "else that has the mod's files open, and run setup again."))
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
            failed.append((game, f"{type(e).__name__}: {e}"))
        if failed and failed[-1][0] == game:
            print(f"\n{game.name} could not be set up: {failed[-1][1]}")
    full = None
    if done:
        full = enable_full_game(config_path(xenia))
        os.makedirs(build, exist_ok=True)
        with open(os.path.join(build, "xenia.txt"), "wb") as f:
            f.write(for_batch(os.path.join(xenia, "xenia_canary.exe")))
    return done, failed, full


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="game, update and DLC files, or folders with them")
    ap.add_argument("--xenia", help="Xenia Canary folder (default: Documents\\Xenia Canary)")
    ap.add_argument("--build", default=os.path.join(ROOT, "build"), help="output folder")
    args = ap.parse_args()

    paths = args.paths or ask_paths(
        "Drag the folder with your game files (or the files themselves) here and press Enter: ")
    print("Looking for the game files:")
    found, _ = find_packages(paths)
    games, notes = plan(found)
    if not games:
        for note in notes:
            print(note)
        sys.exit("No game package (Doritos Crash Course or Doritos Crash Course 2, XBLA) "
                 "was found.")
    xenia = ask_xenia_folder(args.xenia)
    try:
        done, failed, full = run(found, xenia, args.build)
    except SetupError as e:
        sys.exit(str(e))

    print()
    for game in done:
        print(f"Done: start {game.name} with \"{game.play}\".")
    if full:
        print(full)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
