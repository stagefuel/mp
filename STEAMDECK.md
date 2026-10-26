# meikipop on the Steam Deck (Game Mode)

This branch (`gamescope`) adds a **lookup-only meikipop for Steam Deck Game Mode**: hover Japanese text in
a game with the trackpad cursor and the dictionary popup appears over the game. A **Decky Loader plugin**
(`decky/`) controls it from the Quick Access menu: turn it on per game, adjust the popup live, preview.

Desktop Mode on the Deck is just Linux desktop meikipop; see `LINUX.md`. This file is only about Game Mode.

Status: working on a Steam Deck LCD, SteamOS 3.9, Decky Loader 3.3, gamescope 3.16. Not in the Decky
store; the plugin is installed from this repo by hand.

---

## Setup (do these in order)

All commands run on the Deck as the `deck` user, in Desktop Mode's Konsole or over SSH, unless noted.
`sudo` needs a password set with `passwd` first.

### 1. Prerequisites
- **Decky Loader** installed (https://decky.xyz).
- Nothing else: the Flatpak brings Python, Qt, GStreamer and the OCR model. The KDE 6.10 runtime it needs
  is installed from Flathub automatically if missing.

### 2. Install meikipop (Flatpak)
Build it from this branch: the GitHub Actions workflow `.github/workflows/windows-release.yml` has a
manual trigger. Run it with `ref` = `gamescope`; the run's artifact
`meikipop-gamescope-linux-x64-x86_64.flatpak` is a Flatpak bundle (download it, unzip it). Then:

```bash
flatpak install --user -y meikipop-gamescope-linux-x64.flatpak
```
Alternatives the launcher also accepts (checked in this order): `$MEIKIPOP_CMD`, a one-line command in
`~/.config/meikipop/gamescope.cmd` (e.g. a dev checkout, see "Development"), the Linux release binary
at `~/Applications/meikipop/meikipop`, then the Flatpak `io.github.stagefuel.meikipop`.

### 3. Install the launcher
```bash
install -D -m755 packaging/steamdeck/meikipop-gamescope ~/.local/bin/meikipop-gamescope
```
It starts meikipop next to a game (`meikipop-gamescope %command%` as a Steam launch option, which the
plugin sets for you) and stops it when the game exits. `meikipop-gamescope --attach APPID` attaches to a
game that is already running. Log: `~/.local/state/meikipop/gamescope.log`.

### 4. Build and install the Decky plugin
Build anywhere with Node 18+:
```bash
cd decky && npm install && npm run build
```
Copy the result to the Deck as `~/homebrew/plugins/meikipop/` containing `dist/`, `main.py`,
`plugin.json`, `package.json` and `LICENSE` (from the repo root). Decky must be **stopped** while
copying, or the running loader hot-loads the half-copied plugin and leaves orphan processes behind:
```bash
sudo systemctl stop plugin_loader
sudo rm -rf ~/homebrew/plugins/meikipop && sudo cp -r <built folder> ~/homebrew/plugins/meikipop
sudo chown -R root:root ~/homebrew/plugins/meikipop
sudo systemctl start plugin_loader      # Steam's UI reloads
```

### 5. Use it
1. Game Mode → **`…` (Quick Access) → Decky → meikipop**.
2. Under **Use with**, switch a game on (running game first, then the 15 most recently played games).
   If the game is running, meikipop starts at once; otherwise it starts with the game next time.
3. In the game, move the trackpad cursor over Japanese text. With the default settings no key is needed;
   otherwise bind a back button to Shift in the game's controller layout.
4. **Popup** section: text/word size, max width/height (% of the screen), opacity, compact, no-key lookups,
   **Preview**, **Reset**. Changes apply within a second. **On** pauses or resumes all lookups.

For Japanese games under Proton, also set the launch option `LANG=ja_JP.UTF-8 %command%` (the plugin keeps
it: it only inserts its launcher right before `%command%`).

---

## How it works

gamescope (Game Mode's compositor) runs two rootless XWaylands: **`:0` = Steam's UI**, **`:1` = games**.
meikipop is started with the game's environment (`DISPLAY=:1`), with `--gamescope --appid <id>`.

| Piece | How | Code |
|---|---|---|
| Screen capture | gamescope's own PipeWire node, read directly with `pipewiresrc target-object=gamescope` (there's no xdg portal in Game Mode). Overlays aren't in it, so the popup is never OCR'd. Frames are scaled to `:0`'s size. | `src/meikipop/screenshot/gamescope_capture.py` |
| Popup | gamescope only draws extra windows that are on **`:0`** and carry `GAMESCOPE_EXTERNAL_OVERLAY`, and it **stretches them to the whole screen** (like mangoapp's HUD). So the popup is a child of one transparent full-screen host window on `:0` with `GAMESCOPE_NO_FOCUS=1`; the overlay atom is 1 only while a lookup shows. Qt is pointed at `:0` with `-display :0`. | `src/meikipop/gamescope.py`, `gui/popup.py` |
| Cursor | `XQueryPointer` on `:1`, mapped the way gamescope fits the focused window (`GAMESCOPE_FOCUSED_WINDOW` on `:0`) to the screen: scale = min(screen/window), centred. | `src/meikipop/gamescope.py` |
| Pause | Scanning pauses while `GAMESCOPE_FOCUSED_APP` is 769 (Steam's UI) or another game, and while `[GameMode] enabled = false`. | `src/meikipop/gui/gamemode.py` |
| Lifetime | Quits 3 s after its app leaves `GAMESCOPE_FOCUSABLE_APPS` (gives up after 3 min if the game never shows). One instance per game via the X selection `MEIKIPOP_GAMESCOPE_<appid>` on `:0`. | `src/meikipop/gui/gamemode.py`, `gamescope.py` |
| Settings | `gamemode.ini` next to `config.ini`, layered over it in Game Mode only (popup look/size keys in `Config.GAMEMODE_KEYS` plus `[GameMode] enabled`), re-read every second. Game Mode never writes `config.ini`. | `src/meikipop/config/config.py` |
| Plugin | Backend (runs as `deck`): reads/writes `gamemode.ini` (in `~/.config/meikipop/` and the Flatpak's `~/.var/app/io.github.stagefuel.meikipop/config/meikipop/`), touches `gamemode-preview`, finds/starts/stops instances via `/proc`. Frontend: Steam's `SteamClient.Apps.SetAppLaunchOptions` / `SetShortcutLaunchOptions` for the per-game toggle, `RegisterForAppDetails` to read current options. | `decky/main.py`, `decky/src/index.tsx` |

Game Mode is **lookup-only**: no tray, settings window, updater, single-instance socket, Anki mining,
texthooker, copy-line or per-game scan areas, and no X input grabs on the game's display. The whole screen
is scanned.

---

## Invariants (keep these true when changing things)
- **Launch options are never rewritten** beyond adding/removing the launcher before `%command%`; read them
  fresh from Steam right before every change. Env vars, wrappers like `gamemoderun` and trailing args
  survive.
- **meikipop never outlives its game**, however it was started. A killed `distrobox enter` or
  `flatpak run` does NOT kill the process inside, so the self-quit is what guarantees it.
- **Game/instance checks are X-based** (gamescope atoms, X selection), not `/proc`: a Flatpak has its own
  process namespace. Only the plugin backend (outside any sandbox) uses `/proc`.
- **Never `pkill -f`/`pgrep -f` with a pattern that appears in your own command line** (e.g. checking
  for `SteamLaunch AppId=` from a shell whose script text contains it): it matches itself.
- Game Mode never saves `config.ini` (the desktop meikipop shares it).

## Gotchas found while building it
- A window with `GAMESCOPE_EXTERNAL_OVERLAY` on **`:1`** is not shown; on `:0` it is shown full-screen.
- `videorate` in the capture pipeline asserts: gamescope's buffers carry no timestamps.
- `DeckyBackend.call("loader/call_plugin_method", plugin, method, ...args)`: arguments are spread, not a list.
- Plain `notify-send` toasts are silently dropped by Steam in Game Mode for non-game processes.
- Decky's own service uses `KillMode=process`; restarting it can leave plugin processes orphaned and
  growing. A drop-in with `KillMode=mixed` (`/etc/systemd/system/plugin_loader.service.d/`) fixes that.
- Running long jobs on the Deck over SSH: use `systemd-run --user`, not `nohup`.

## Testing checklist
1. Plugin: switch a game on with no game running → launch it → popup works.
2. With the game running: switch it off → meikipop stops at once; on → starts at once.
3. Switched off, launch options empty → launch → **no** popup (nothing left running from before).
4. Quit the game → meikipop quits within a few seconds; relaunch → exactly one instance.
5. Sliders change the popup within a second; Preview shows a sample; **On** off → no lookups.
6. Open the Quick Access menu during a game → no popups over Steam's UI.

## Development
Run from source without building a Flatpak: a distrobox (e.g. `fedora-toolbox:42`) with
`python3-gobject gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good pipewire-gstreamer
python3-evdev google-noto-sans-cjk-fonts` and the Qt xcb libraries, a venv with
`--system-site-packages` and `pip install -e . onnxruntime`, then put
`distrobox enter <box> -- <checkout>/.venv/bin/meikipop` in `~/.config/meikipop/gamescope.cmd`.
Start-up is ~15 s that way (vs ~5 s for the Flatpak). OCR on the Deck's CPU: ~0.16 s per scan.
