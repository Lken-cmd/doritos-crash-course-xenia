"""Build the release zip (setup and tools; no build output or game files).

Refuses uncommitted release files unless --allow-dirty (test builds).

usage: python make_release.py <version> [--allow-dirty]
       (writes dist/doritos-crash-course-xenia-<version>.zip)"""
import argparse
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "doritos-crash-course-xenia"
FILES = ["LICENSE", "README.md", "requirements.txt", "setup.bat",
         "Play Doritos Crash Course.bat", "Play Doritos Crash Course 2.bat"]
FOLDERS = {"patches": (".toml",), "tools": (".py", ".bat")}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.splitlines()


def is_release_file(rel):
    folder, _, name = rel.rpartition("/")
    return rel in FILES or (folder in FOLDERS and name.endswith(FOLDERS[folder]))


def release_files():
    """Repo-relative paths git tracks or would add (ignored files never ship),
    in zip order."""
    files = {f for f in git("ls-files", "--cached", "--others", "--exclude-standard")
             if is_release_file(f)}
    missing = [f for f in FILES if f not in files]
    if missing:
        sys.exit(f"missing: {missing}")
    return list(FILES) + sorted(files - set(FILES))


def main(version, allow_dirty):
    files = release_files()
    dirty = [line[3:].strip('"') for line in git("status", "--porcelain", "--", *files)]
    if dirty and not allow_dirty:
        sys.exit("Commit these first (or use --allow-dirty for a test build):\n  "
                 + "\n  ".join(dirty))
    top = f"{NAME}-{version}"
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, top + ".zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            with open(os.path.join(ROOT, *rel.split("/")), "rb") as f:
                data = f.read()
            if rel.endswith(".bat"):  # cmd.exe misreads some batch files with LF line ends
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(f"{top}/{rel}", data)
    print(f"{out}: {len(files)} files" + (" (with uncommitted changes)" if dirty else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("version", help="e.g. 1.0.0")
    ap.add_argument("--allow-dirty", action="store_true", help="build with uncommitted changes")
    a = ap.parse_args()
    main(a.version, a.allow_dirty)
