# Doritos Crash Course in Xenia

Play **Doritos Crash Course**
in the [Xenia Canary](https://github.com/xenia-canary/xenia-canary)
emulator. The game uses Xbox avatars as its characters, which Xenia can't
draw, so the players were invisible. This mod fixes that.

You need your own copy of the game. The mod is built from your game files;
this repository contains none.

## What works

- Up to 4 players, each in their own outfit, as the game's built-in stand-in character.
- The City Lights DLC.

## What you need

1. **The game files.** Setup recognizes them by their content, so file names
   don't matter and `.zip` files are fine.

   | Package | Needed? | File name on an Xbox drive |
   |---|---|---|
   | Doritos Crash Course | yes | `AC156E0F6A8E78FA306375D57C1210050E46DE4E58` |
   | Doritos Crash Course Title Update 2 | recommended: DLC, player numbering | `tu00000002_00000000` |
   | Doritos Crash Course City Lights (DLC) | optional, needs Title Update 2 | `5C5E4648EC4191422AD927380710447E3968017158` |

2. **[Xenia Canary](https://github.com/xenia-canary/xenia-canary).** Unpack
   it (for example to `Documents\Xenia Canary`), start it once and close it.
3. **[Python](https://www.python.org/downloads/) 3.8 or newer**, installed
   with the default options.

## Install

1. Download `doritos-crash-course-xenia-<version>.zip` from
   [Releases](https://github.com/Lken-cmd/doritos-crash-course-xenia/releases)
   and unpack it to a folder you keep.
2. Double-click **`setup.bat`**
3. Add your game files (*Add files…* or *Add folder…*) and check that the
   Xenia Canary folder is right.
4. Close Xenia and click **Install**. It takes a minute or two.

Then play with the button at the end of the setup, or with
`Play Doritos Crash Course.bat`.

## Limitations

- Everyone is the game's stand-in character, not your own Xbox avatar.
- Tested with Xenia Canary `02d2cb5` on Direct3D 12.

## How it was made

I made this with a lot of help from AI Claude. Most of the reverse engineering, the Xenia patches and the
scripts in `tools/` came out of working on it together.

## Legal

Unofficial fan project, not affiliated with Microsoft or the
game's developers. Doritos and Xbox are trademarks of their owners.
