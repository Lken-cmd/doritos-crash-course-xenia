# Doritos Crash Course 1 & 2 in Xenia

Play **Doritos Crash Course** and **Doritos Crash Course 2** 
in the [Xenia Canary](https://github.com/xenia-canary/xenia-canary)
emulator. Both games use Xbox avatars as their characters, which Xenia can't
draw, so the players were invisible and Crash Course 2 needs online servers, which are long offline.
This mod fixes that, and gets Crash Course 2 running without its servers.

You need your own copy of the games. The mod is built from your game files;
this repository contains none.

## What works

**Doritos Crash Course**
- Up to 4 players, each in their own outfit, as the game's built-in stand-in character.
- The City Lights DLC.

**Doritos Crash Course 2**
- World Tour works offline, with the AI racers.
- Earn stars in races and spend them on new courses. Progress is saved in your Xenia profile. 
Coins (real money in the original) are gone.
- Local multiplayer

## What you need

1. **The game files.** Setup recognizes them by their content, so file names
   don't matter and `.zip` files are fine.

   | Package | Needed? | File name on an Xbox drive |
   |---|---|---|
   | Doritos Crash Course | for Crash Course | `AC156E0F6A8E78FA306375D57C1210050E46DE4E58` |
   | Doritos Crash Course Title Update 2 | recommended: DLC, player numbering | `tu00000002_00000000` |
   | Doritos Crash Course City Lights (DLC) | optional, needs Title Update 2 | `5C5E4648EC4191422AD927380710447E3968017158` |
   | Doritos Crash Course 2 | for Crash Course 2 | `92EC7B55A94EF2145A233412B18261DEA2BAE65858` |
   | Doritos Crash Course 2 Title Update 2 | for Crash Course 2 | `tu00000002_…` |

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
4. Close Xenia and click **Install**. It takes a minute or two per game.

Then play with the buttons at the end of the setup, or with
`Play Doritos Crash Course.bat` / `Play Doritos Crash Course 2.bat`. Sign in
with a Xenia profile (*Profile* menu) so your progress is saved.

## Options (Crash Course 2)

Open `5841124F - Doritos Crash Course 2 (offline).patch.toml` in Xenia's
`patches` folder and set `is_enabled = true` under:
- *Unlock all courses*: every course open, no stars needed.
- *Race solo (no AI racers)*: World Tour without the AI racers.

Running the setup again keeps these settings.

## Limitations

- Everyone is the games' stand-in character, not your own Xbox avatar.
- Nothing online works in Crash Course 2: online play, leaderboards, Time
  Trials, Avatar FameStar and the Avatar Store. Some Shop tabs are empty because their items came from the servers.
- Tested with Xenia Canary `02d2cb5` on Direct3D 12.

## How it was made

I made this with a lot of help from AI Claude. Most of the reverse engineering, the Xenia patches and the
scripts in `tools/` came out of working on it together.

## Legal

Unofficial fan project, not affiliated with Microsoft or the
games' developers. Doritos and Xbox are trademarks of their owners.
