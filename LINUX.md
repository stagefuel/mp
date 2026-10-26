# Linux support (work in progress, branch `linux`)

Target: **KDE Plasma 6 on Wayland** (Aurora / Bazzite / Fedora KDE), games under Wine via XWayland.
Test machine: **the test laptop** (ThinkPad T470s, Aurora 44, KWin 6.7, 1920x1080 @ 100 %).

## Tested on the test laptop, 2026-10-10 (from source in a distrobox, driven remotely)
Works on Wayland, over an XWayland window (Firefox run with `--nosocket=wayland --socket=x11`):
- KDE's "Share screen with" prompt appears on first start; with *Allow restoring* ticked it isn't asked again,
  also after restarting meikipop. Tray shows KDE's recording indicator while meikipop runs.
- OCR on the T470s CPU: ~0.5–1.4 s per scan. Hover lookups correct; the popup lands 15 px below-right of the
  cursor (100 % scaling; other scale factors untested). JL layout, Noto Sans CJK JP render fine.
- Middle click locks (all entries, scrollable, footer hint), wheel scrolls the popup and not the page,
  clicking an entry mines it (Anki wasn't running: the footer said so), Esc unlocks.
Bugs found and fixed on this branch:
- Wayland capture never started on current PyGObject (`GLib.MainLoop.new` needs `is_running`).
- "Only Show After Mouse Moves" swallowed the first correct popup after any screen change, because the scan
  a mouse move starts finishes after the mouse stops (~1 s on this CPU). Scans now carry the mouse position
  of their screenshot. (Affects Windows too.)
Known gaps confirmed:
- Over Wayland-native windows (Konsole) meikipop sees a frozen cursor position → no lookups (to do #3).
- ~18 % of one core while idle: the 30 fps screen stream itself (to do #4: lower rate / window stream).
- First-run dictionary download 404s: upstream's `dictionary-latest` release no longer exists (affects every
  fresh install on every OS, not just Linux).
- In the distrobox, pynput's `evdev` dependency needs Fedora's `python3-evdev` (no compiler in the box).

## How meikipop runs on Linux today (upstream)
- X11: native. Wayland: meikipop forces itself onto **XWayland** (`QT_QPA_PLATFORM=xcb`) so its popup can
  place itself anywhere, and takes screenshots through the **ScreenCast portal + PipeWire** (KDE asks once;
  the choice is remembered with a restore token).
- Capture delay on Wayland: frames come from a live stream (≤30 fps), so a "screenshot" is the latest
  frame, ~20–60 ms old, and grabbing it takes ~0 ms. OCR (100–600 ms) dominates either way.
- Limits on Wayland: the cursor position, the hotkey, middle click and Esc are only visible while the
  pointer/focus is on an **X11/XWayland** window (e.g. a Wine game) — not over Wayland-native apps
  (Firefox, Okular, …).

## Done on this branch (untested on hardware unless noted)
- [x] Default popup font per OS (Noto Sans CJK JP on Linux, Segoe UI on Windows, Hiragino Sans on macOS)
- [x] Wayland capture copies a frame only when a screenshot is requested (was: every frame of the stream,
      up to 30 full-screen copies per second in the background)
- [x] X11/XWayland: while the popup is up, middle click (and Esc while locked) are grabbed so the game
      under the cursor doesn't act on them; meikipop still sees them. **Tested under Xvfb** with a stand-in
      X11 window: the window stops getting middle/Esc only while the popup is up, left clicks still pass.
- [x] Release workflow also builds a single-file **Linux x86_64 binary** (Ubuntu 22.04, self-tested under
      Xvfb). It's for X11 sessions: Wayland capture needs PyGObject + GStreamer, which don't bundle well.

## Wayland investigation (the test laptop, 2026-10-10) — what "fully functional" needs on KDE
| Piece | Today | Fix (KDE Plasma 6) | Status |
|---|---|---|---|
| Cursor position over Wayland-native windows | frozen (XWayland only sees X11 windows) | **KWin script** (`gui/kwin_cursor.py`, loaded over D-Bus at start on KDE Wayland, unloaded on exit) | **done + tested**: popups over Konsole at the right spot, ~10–25 ms |
| Hotkey (Shift) and Esc over native windows | **already work** — KDE's default *Legacy X11 App Support* lets X11 apps see modifier keys and Esc (not letters) | — | tested |
| Mouse buttons (middle-click lock, click-outside close) over native windows | not seen by meikipop | **double-tap the hotkey** locks/unlocks (setting, on by default; works on Windows too); optional KDE setting *Legacy X11 App Support → include mouse buttons* for middle click | **done + tested** over Konsole |
| Keeping middle click away from native apps | impossible (X grabs only affect X11 apps); in Konsole/Firefox a middle click pastes the selection | use the double-tap on Wayland | by design |
| Popup placement over native windows | used `QCursor.pos()` (frozen there) | uses the KWin position | **done + tested** |
| Idle CPU | was ~16 % of one T470s core — **not** the screen stream (10 vs 30 fps made no difference) but the 100 Hz polling | popup skips work while hidden; cursor from KWin instead of an X round trip | **done: ~8 %** |
| Display scaling ≠ 100 %, multi-monitor | untested | test, then map portal pixels ↔ XWayland coordinates | to do (needs a scale change on the test box) |
| Region selector overlay on Wayland | — | — | **tested**: overlay, drag, offset hover all correct |
| Focused window (per-game scan areas, pause outside games) | XWayland only sees X11 windows | the same KWin script also reports `workspace.windowActivated` (instance/class like X11, so saved games match on either) | done, untested on hardware |
| Copy-line hotkey (ctrl+alt+c) | pynput global hotkey | works over X11/XWayland windows (games under Wine); KDE doesn't pass letter keys to X11 apps over native windows — use tray → Copy Line there | done, untested on hardware |
| Run on startup | — | `~/.config/autostart/meikipop.desktop` (flatpak: `--filesystem=xdg-config/autostart:create`, Exec `flatpak run …`) | done, tested from source on X11 |
| GNOME | no KWin scripting; would need a GNOME Shell extension or ScreenCast cursor metadata | out of scope for now | — |
| Packaging | distrobox from source | Flatpak (KDE runtime has GStreamer/PipeWire); needs `--talk-name=org.kde.KWin` for the script | done: built in CI, released as a pre-release; install test on the test laptop pending |

## To do
1. **Run it on the test laptop** (from source in a distrobox, below) and check:
   - [ ] KDE's screen-capture prompt appears once and is remembered
   - [ ] hover lookups over a Wine/XWayland window; popup lands under the cursor
   - [ ] display scaling (125/150 %) and multi-monitor: capture pixels vs XWayland coordinates may not match
         → popup or hit scan off by the scale factor
   - [ ] middle click lock / mining / Esc / scrolling the locked popup; the grab keeps them from the game
   - [ ] texthooker to kizuna, AnkiConnect
   - [ ] onnxruntime speed (CPU build; CUDA build optional)
2. **evdev input backend** (hotkey, middle click, Esc from `/dev/input`): works over Wayland-native apps too
   and on any compositor. Needs the user in the `input` group (or a udev rule).
3. **Cursor position over Wayland-native apps**: a small KWin script reporting `workspace.cursorPos` over
   D-Bus (KDE only); alternative: ScreenCast `cursor_mode=metadata` (any compositor, needs a PipeWire reader
   that exposes cursor metadata — GStreamer's pipewiresrc doesn't).
4. Lighter capture: stream only the game's **window** (portal source type 2) instead of the monitor; lower
   the frame rate when idle.
5. **Flatpak** (upstream has `flatpak/manifest.yml`): the natural package for Aurora/Bazzite and the only
   easy way to ship Wayland capture. Needs `--share=network`, x11 + wayland sockets, the ScreenCast portal,
   and `--device=input` (or `all`) for evdev.

## Running from source on Aurora/Bazzite (distrobox)
```bash
distrobox create -i registry.fedoraproject.org/fedora:44 -n meikipop
distrobox enter meikipop
sudo dnf install -y python3 python3-pip python3-gobject gstreamer1 gstreamer1-plugins-base \
    gstreamer1-plugins-good pipewire-gstreamer libxcb xcb-util-cursor xcb-util-wm xcb-util-keysyms \
    libxkbcommon-x11 google-noto-sans-cjk-fonts python3-evdev git
git clone -b linux <repo> meikipop && cd meikipop
python3 -m venv --system-site-packages .venv && . .venv/bin/activate   # system site: python3-gobject
pip install -e .
meikipop
```
