# Doritos Crash Course: visible players in Xenia

Xenia can't draw Xbox 360 avatars, so the runners in Doritos Crash Course
(XBLA, `58410A71`) are invisible. This mod replaces them with the game's
built-in stand-in character, one shirt colour per player.

Mostly data files are changed. The executable stays untouched on disk; a
small Xenia patch file fixes the player colours in memory. This repo
contains no game files.

## Features

- 4 visible players: P1 blue, P2 red, P3 green, P4 yellow (runners, ghost,
  lobby, credits)
- A runner's shirt matches their lobby frame, HUD and billboard (Xenia
  patch, needs Title Update 2)
- City Lights DLC, through Title Update 2
- Multiplayer helicopter billboards show the players
- No Xbox LIVE messages before matches or on the results screen

## Requirements

- Your own copies of the game (XBLA package) and, for the DLC, Title
  Update 2 (v0.0.2.2, media ID `261A2859`) and City Lights. `.zip` files
  are fine.
- [Xenia Canary](https://github.com/xenia-canary/xenia-canary), started
  once so it creates its config file.
- [Python](https://www.python.org/downloads/) 3.8 or newer.

## Setup

1. Double-click `setup.bat`, or drag the folder with your game files onto it.
2. Enter your game files (any order) and, if it isn't
   `Documents\Xenia Canary`, your Xenia folder.

Setup builds the mod into `build\`, installs the update, the DLC and the
patch file into Xenia, and sets `license_mask = 1` (full game instead of
the trial).

## Play

Double-click `Play Doritos Crash Course.bat`. To use a different Xenia, set
the `XENIA` environment variable to its `xenia_canary.exe`.

## Manual install

```
pip install -r requirements.txt
python tools\build_mod.py <game> build [<title update>]
python tools\install_content.py <title update> <Xenia folder> --override-dir build\update
python tools\install_content.py <DLC> <Xenia folder>
copy "patches\58410A71 - Doritos Crash Course.patch.toml" "<Xenia folder>\patches\"
```

`<Xenia folder>` is Xenia's own folder in portable mode (`portable.txt`
next to the exe), otherwise `Documents\Xenia`. The patch needs
`apply_patches = true` in Xenia's config (the default).

## How it works

- **Players:** Xbox avatar references (`XAVT:<name>`) in `fighter.wbr`,
  `guiresource.wbr` and the precache lists become `BNMD:_avatar/player<N>.cfg`,
  a normal Cal3D model.
- **Textures:** recoloured shirts and drawn eyes, mouth and brows, with the
  shaders the Xbox data lacks.
- **Skin:** the clothes get the body's bone weights. Covered skin is tucked
  in by 0.5–4 cm and removed if more than 7 cm from exposed skin; the neck
  is never removed (`hidden_skin.py`).
- **Billboards:** the game's live renders come out as garbage in Xenia, so
  they are replaced with pictures rendered at build time in animation poses
  (`pose.py`, `render.py`).
- **LIVE messages:** reads of the Lua global `postingGameInLive` become
  `false`, so matches start as local matches (`lua51.py`). The results
  screen's leaderboard text is blanked.
- **Title update:** the same changes are applied on top of its `patch.pak`.
- **Player colours:** the HUD, progress bar and billboards are coloured by
  race slot, but the game picked the runner by controller, and it numbered
  the race slots in join order while the lobby shows each player in their
  controller's frame. The patch file has the runner follow the slot and sorts
  the race slots by controller. So all colours agree whenever controllers
  1..N play; with controller 1 unused, the race colours start at P1 blue
  anyway.

| File | Purpose |
|---|---|
| `patches/58410A71 - Doritos Crash Course.patch.toml` | Xenia patch: player colours (for Title Update 2) |
| `setup_mod.py` | finds the packages, builds, installs, configures Xenia |
| `build_mod.py` | builds `build/game/` and `build/update/` |
| `install_content.py` | installs a package into Xenia's content folder |
| `verify_build.py` | checks a build, renders `build/preview/players.png` |
| `avatar.py` | the stand-in model's layout |
| `hidden_skin.py` | fits the clothes, tucks in and removes covered skin |
| `pose.py`, `render.py` | animation poses and software rendering |
| `make_textures.py` | shirt colours and face textures |
| `lua51.py` | patches compiled Lua 5.1 scripts |
| `stfs.py`, `tongaspak.py`, `wbr.py`, `cal3d.py` | file formats: packages, `data.pak`, templates, models |

## Limitations

- Tested with Xenia Canary `02d2cb5` (Direct3D 12). That build needs
  extracted content folders with `0x148`-byte headers, which
  `install_content.py` writes; newer builds accept them too.

## Legal

Unofficial fan project, not affiliated with Microsoft, Frito-Lay or the
game's developers. Doritos and Xbox are trademarks of their owners.
