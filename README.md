# meikipop - universal japanese ocr popup dictionary

instantly look up japanese words anywhere on your screen. meikipop uses optical character recognition (ocr) to read text from websites, games, scanned manga, or even hard-coded video subtitles, giving you effortless dictionary lookups with the press of a key (or even without)!

https://github.com/user-attachments/assets/a1834197-3059-438c-a2dc-716e8ec9078f



## this fork (stagefuel/meikipop)

based on upstream v2.0.5, with:

*   **always below cursor:** a popup position mode that never jumps above the mouse; long lookups are cut to fit instead.
*   **max popup size:** max popup width/height (% of screen) in settings → general.
*   **jl-style popup:** settings → popup appearance → layout "JL" + preset "JL" (word, reading, conjugation like `撫でている ～teiru`, frequency, one line per meaning). settings → general → frequency list can point at JL's `freqlist_vns.json` (or any nazeka-format list) so the numbers match JL.
*   **texthooker feed:** settings → general → texthooker (websocket) serves each new ocr'd line on `ws://localhost:9001` (the port textractor/lunahost use) for pages like kizuna-texthooker-ui. lines are only sent once they've read the same in 2 scans (no half-typed text), never resent while still on screen, only the new part is sent if a line keeps growing, and nothing is replayed when the page reloads. needs auto scan; while it's on, scans don't wait for the mouse to move. scan just the text box so menus/other windows aren't sent. don't run it at the same time as another program serving on the same port.
*   **anki mining (like [JL](https://github.com/rampaa/JL)):** middle click while a popup is open to lock it in place. while locked, ocr and lookups are paused, every entry is shown (scrollable), and left clicking an entry adds it to anki through [AnkiConnect](https://ankiweb.net/shared/info/2055492159). esc, middle click, or clicking anywhere outside the popup closes it. on windows the middle click and esc are swallowed so the game underneath doesn't react to them. deck, note type, tags, duplicates and the field mapping (word, reading, definitions, reading + definitions, first definition, sentence, part of speech, frequency) are in settings → anki; out of the box it adds to the `Default` deck as a `Basic` card (front: word, back: reading + definitions). definitions are formatted like JL's: `(1) (n) gloss; gloss<br/>(2) ...`.

## features

*   **works everywhere:** if you can see it on your screen, you can look it up. no more limitations of browser extensions, hooks or application-specific tools.
*   **ocr-powered:** reads japanese text directly from images, making it perfect for games, comics, and videos.
*   **blazingly fast:** the dictionary is pre-processed into a highly optimized format for instant lookups. the ui is designed to be lightweight and responsive.
*   **simple & intuitive:** just point your mouse and press a hotkey. that's it.
*   **highly customizable:** change the hotkey, theme, colors, and layout to create your perfect reading experience.
*   **region or fullscreen:** scan your entire screen or select a specific region (like a game window or manga page) to improve performance.
*   **pluggable ocr backend:** lets you choose whatever ocr suits you best. whether you want the highest accuracy remote ocr, that runs great even on low-end hardware or you want blazingly fast and private local ocr.

## philosophy & limitations

meikipop is designed to do one thing and do it exceptionally well: provide fast, frictionless, on-screen dictionary lookups.

it is heavily inspired by the philosophy of [Nazeka](https://github.com/wareya/nazeka), a fantastic browser-based popup dictionary, and aims to bring that seamless experience to the entire desktop. it also draws inspiration from the ocr architecture of [owocr](https://github.com/AuroraWright/owocr/tree/master/owocr).

to maintain this focus, there are a few things meikipop is **not**:

*   **it is not an srs-mining tool.** meikipop does not include functionality to automatically create flashcards for programs like anki.
*   **it is not a multi-dictionary tool.** while meikipops lets you import yomitan dictionaries, it is designed to run best with a single, semi-custom jmdict+kanjidic dictionary. 

## installation

note that when meikipop is started for the first time, the dictionary (~40 mb) and the ocr model are downloaded, so it needs an internet connection once.

### easiest: windows exe

1. download `meikipop-<version>-windows-x64.exe` from this repo's [releases](https://github.com/stagefuel/mp/releases/latest). no python needed, nothing to install or unpack.
2. put it wherever you like (e.g. `C:\Programs\meikipop\`) and run it. windows smartscreen may warn that it's from an unknown publisher since it isn't code-signed: *more info → run anyway*.
3. a console window opens next to the tray icon; leave it open (closing it quits meikipop). settings, the dictionary and a log of the last session (`meikipop.log`) are kept in `%LOCALAPPDATA%\meikipop`.
4. the first time, select the part of the screen to scan (see [how to use](#how-to-use)).

to update, quit meikipop from the tray and replace the exe; settings are kept.

### from source (any platform)

requires python 3.10+ and access to this repo. note that `pip install meikipop` installs upstream meikipop, which doesn't have this fork's features.

```bash
#... activate your environment if any
git clone https://github.com/stagefuel/mp.git meikipop
cd meikipop
pip install -e .
meikipop  # run the application
```

to build the windows exe yourself: `pip install pyinstaller`, then `pyinstaller --noconfirm meikipop.win.x64.spec` (the exe ends up in `dist\`).

### setting up this fork's extras

* **anki mining:** install the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code `2055492159`) and keep anki running. out of the box, cards go to the `Default` deck as `Basic` notes; pick your own deck, note type and what goes in each field in *settings → anki* (*load decks & note types from anki* fills the lists). to mine: hover a word, **middle click** to lock the popup, **click an entry**; the bottom line turns green when it's added and red if it's already in anki. esc, middle click or clicking elsewhere closes it.
* **texthooker (websocket):** tick *settings → general → texthooker → send new lines* and point your texthooker page (e.g. kizuna-texthooker-ui) at `ws://localhost:9001`. set the scan area to just the game's text box, keep auto scan on, and don't run textractor/lunahost on the same port at the same time.
* **jl look:** the popup layout defaults to jl's. to show the same frequency numbers as jl, set *settings → general → frequency list* to jl's `Resources\freqlist_vns.json` (or any nazeka-format list).

### platform support

* **windows, linux (x11)** - these are the primary supported platforms
* **macos** - supported thanks to community contributions
* **linux (wayland)** - it can work in principle thanks to community contributions, but may require additional trouble shooting

see for platform specific setup details:
<details>
<summary>macos</summary>

* go to **System Preferences** > **Security & Privacy** > **Privacy**
* add/enable your terminal app in **Input Monitoring**, **Screen Recording** and **Accessibility**

note that there may be problems when using python 3.14. use one of [these workarounds](https://github.com/rtr46/meikipop/issues/43) if necessary.
</details>

<details>
<summary>wayland (alpha)</summary>

it is possible to run meikipop on wayland in principle, but depending on your specific setup you may need to take additional steps like installing additional dependencies, fixing some of the wayland specific code or changing some of your setup. since the wayland eco system is terribly fragmented and deliberately prevents apps like meikipop from working natively, don't expect any support, but feel free to open an issue regardless.

here are some tips and recommendations:
* consider switching to x11
* the easiest and most compatible way is trying to run the flatpak distribution of meikipop first, before trying any of the other tips 
* if the flatpak does not work for you, install via pypi or create an editable install and avoid the linux prebuilt, which only got tested on x11
* make sure you have xwayland working
* you may need to install additional python dependencies, depending on your system like `pip install pygobject`
* you may need to install additional os dependencies, depending on your distribution like:
  * fedora: `sudo dnf install libxcb xcb-util xcb-util-cursor libxkbcommon-x11 libxkbcommon xcb-util-wm xcb-util-keysyms pipewire-gstreamer`
  * ubuntu: `sudo apt install cmake libcairo2-dev libgirepository-2.0-dev libgstreamer1.0-dev gstreamer1.0-pipewire libxcb-xkb-dev libxcb-cursor-dev libxcb-xinerama0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1-dev libxcb-shape0`
* if meikipop is running, but doesn't show any popups, make sure to test lookups on a windowed xwayland application like steam
* ask your favorite llm for help
</details>

## how to use

1.  run the application (`meikipop`).
2.  the first time you run the app in `region` mode, you will be prompted to select an area of your screen to scan.
3.  move your mouse over any japanese text on your screen.
4.  a popup with dictionary entries will appear.
5.  **right-click the system tray icon** to open the settings, reselect the scan region, change the ocr provider or quit the application.
6.  to add a word to anki, **middle click** while its popup is open, then **click the entry** (see [setting up this fork's extras](#setting-up-this-forks-extras)).

## configuration

you can fully customize meikipop's behavior and appearance. right-click the tray icon and choose "settings" to open the configuration gui.

changes are saved to a platform-specific user data directory which contains `config.ini` and `dictionary.pkl`:
- windows: `%LOCALAPPDATA%\meikipop\`
- linux: `~/.config/meikipop/`
- macos: `~/Library/Application Support/meikipop/`

## using alternative ocr backends...

meikipop's architecture allows you to choose whatever ocr suits your use case best:
- meikiocr (default/local): possibly the fastest local ocr worth using on cpu and can run even faster on nvidia gpus. primarily designed for video games with horizontal text. poor accuracy for vertical text.
- google lens (remote): high accuracy, but requires an internet connection and has higher latency then the local options.
- chrome screen ai (local): alternative local ocr worth checking out if meikiocr does not fit your use case. requires additional setup ([instructions](https://github.com/rtr46/meikipop/releases/tag/v1.10.0))
- owocr: owocr lets you choose from even more ocr backends (see below)
- custom ocr provider: if you are running from source it is very simple to integrate any ocr provider on your own (see below) 

### ...via owocr provider

owocr lets you run any relevant ocr engine and lets meikipop use it. just run a local [owocr](https://github.com/AuroraWright/owocr/tree/master/owocr) instance and select the owocr ocr provider from meikipop's system tray menu.

make sure you:

* use owocr 1.15.0 or newer
* enable reading from and writing to websockets
* choose the json output format
* and use an ocr backend that supports coordinates (most do)
    ```bash
    pip install -U "owocr>=1.15"
    owocr -r websocket -w websocket -of json -e glens # replace glens with your favorite owocr backend
    ```

### ...via custom ocr provider

you can develop your own ocr provider. to get started, you can copy the `dummy` provider and use it as a template.

for a complete guide, see: [how to create a custom ocr provider](docs/CUSTOM_OCR_PROVIDER.md)

## building your own dictionary (optional)

in case you want to update your dictionary you can simply run:

```bash
meikipop build-dict
```

if you want to import a yomitan dictionary that is possible as well. you can import multiple yomitan dictionaries at once, but be aware that this will overwrite your default dictionary:

```bash
# try to keep as much of the dictionary's original formatting
meikipop import-yomitan-dict-html my_yomitan_dict.zip
# or create a compact, text only dictionary
meikipop import-yomitan-dict-text my_yomitan_dict.zip
# or import multiple dictionaries at once
meikipop import-yomitan-dict-text dict1.zip dict2.zip
```

## license

meikipop is licensed under the GNU General Public License v3.0. see the `LICENSE` file for the full license text.


