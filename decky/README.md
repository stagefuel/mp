# meikipop Decky plugin

Quick Access panel for meikipop's **Steam Deck Game Mode** lookup popup (`meikipop --gamescope`,
see LINUX.md → "Steam Deck Game Mode"). Not in the Decky store: the source is here on branch `gamescope`, and it's built and installed by hand.
**Full setup guide: [../STEAMDECK.md](../STEAMDECK.md).**

## What it does
- **On**: pause/resume lookups live (`[GameMode] enabled` in `gamemode.ini`).
- **Use with**: toggle per game (running game first, then the 15 most recently played). Only adds or
  removes `/home/deck/.local/bin/meikipop-gamescope` right before `%command%` in the game's launch
  options. Launch options are re-read from Steam right before every change and everything else in
  them is kept (tested: env vars, `gamemoderun`, trailing args; a bare `%command%` comes back empty,
  which Steam treats the same). If the game is running, meikipop is also started
  (`meikipop-gamescope --attach APPID`, with the game's environment copied from its reaper process)
  or stopped right away.
- **Popup** sliders/toggles: text/word size, max width/height %, opacity, compact, no-key lookups.
  Written to `~/.config/meikipop/gamemode.ini`, which Game Mode meikipop re-reads every second.
  Desktop meikipop never reads that file.
- **Preview**: touches `~/.config/meikipop/gamemode-preview`, meikipop shows a sample lookup for 6 s.

## Build and install
```bash
cd decky && npm install && npm run build
# copy dist/ main.py plugin.json package.json ../LICENSE into ~/homebrew/plugins/meikipop (root:root)
# Decky must be STOPPED while copying (else the running loader hot-loads it and orphans processes):
sudo systemctl stop plugin_loader; ...copy...; sudo systemctl start plugin_loader
```
Backend runs as the `deck` user (no `root` flag). Calls from the frontend are spread:
`DeckyBackend.call("loader/call_plugin_method", "meikipop", "set_setting", key, value)`.
