# Linux support (work in progress, branch `linux`)

Target: **KDE Plasma 6 on Wayland** (Aurora / Bazzite / Fedora KDE), games under Wine via XWayland.
Test machine: **100shiki** (Aurora). Nothing on this branch has been tried on a real Linux desktop yet.

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

## To do
1. **Run it on 100shiki** (from source in a distrobox, below) and check:
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
    libxkbcommon-x11 google-noto-sans-cjk-fonts git
git clone -b linux <repo> meikipop && cd meikipop
python3 -m venv --system-site-packages .venv && . .venv/bin/activate   # system site: python3-gobject
pip install -e .
meikipop
```
