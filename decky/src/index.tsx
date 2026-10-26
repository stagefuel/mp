// meikipop Decky plugin - Quick Access panel for meikipop's Game Mode lookup popup.
// Settings go to ~/.config/meikipop/gamemode.ini via the backend (main.py); a running Game Mode
// meikipop re-reads it every second, so every change shows on the next lookup.
import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  Router,
  SliderField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";
import { FaBook } from "react-icons/fa";

type Settings = {
  enabled: boolean;
  font_size_definitions: number;
  font_size_header: number;
  popup_max_width_percent: number;
  popup_max_height_percent: number;
  background_opacity: number;
  compact_mode: boolean;
  auto_scan_mode_lookups_without_hotkey: boolean;
};
type Status = { wrapper: string; wrapper_installed: boolean; meikipop: string };

const getSettings = callable<[], Settings>("get_settings");
const setSetting = callable<[key: string, value: number | boolean], boolean>("set_setting");
const resetSettings = callable<[], boolean>("reset_settings");
const preview = callable<[], boolean>("preview");
const getStatus = callable<[], Status>("status");
const isRunning = callable<[appid: number], { game: boolean; meikipop: boolean }>("running");
const startFor = callable<[appid: number], boolean>("start_for");
const stopFor = callable<[appid: number], boolean>("stop_for");

declare const SteamClient: any;
declare const appDetailsStore: any;
declare const appStore: any;

// --- per-game launch option ---------------------------------------------------------------
const NON_STEAM = 1073741824; // app_type of non-Steam shortcuts

// Steam loads a game's details (incl. launch options) on request; works for games that aren't running
function readLaunchOptions(appid: number): Promise<string> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (value: string) => {
      if (done) return;
      done = true;
      try { handle?.unregister(); } catch { /* already gone */ }
      resolve(value);
    };
    const handle = SteamClient.Apps.RegisterForAppDetails(appid, (d: any) => finish(d?.strLaunchOptions ?? ""));
    setTimeout(() => finish(appDetailsStore?.GetAppDetails(appid)?.strLaunchOptions ?? ""), 3000);
  });
}

function withWrapper(opts: string, wrapper: string): string {
  if (opts.includes(wrapper)) return opts;
  if (opts.includes("%command%")) return opts.replace("%command%", `${wrapper} %command%`);
  return `${wrapper} %command% ${opts}`.trim();
}

function withoutWrapper(opts: string, wrapper: string): string {
  const out = opts.split(`${wrapper} `).join("").trim();
  return out === "%command%" ? "" : out;
}

function setLaunchOptions(appid: number, opts: string) {
  const isShortcut = appStore?.GetAppOverviewByAppID(appid)?.app_type === NON_STEAM;
  if (isShortcut) SteamClient.Apps.SetShortcutLaunchOptions(appid, opts);
  else SteamClient.Apps.SetAppLaunchOptions(appid, opts);
}

// recently played games and non-Steam shortcuts, newest first
function recentGames(): { appid: number; name: string }[] {
  return [...appStore.allApps]
    .filter((a: any) => (a.app_type === 1 || a.app_type === NON_STEAM) && a.rt_last_time_played > 0)
    .sort((a: any, b: any) => b.rt_last_time_played - a.rt_last_time_played)
    .slice(0, 15)
    .map((a: any) => ({ appid: Number(a.appid), name: a.display_name }));
}

// on/off for one game: only adds or removes the wrapper, never touches the rest of its launch options.
// If the game is running, meikipop is also started/stopped right away instead of at its next launch.
function GameToggle({ appid, name, status, running }: { appid: number; name: string; status: Status; running?: boolean }) {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    setOn(null);
    readLaunchOptions(appid).then((opts) => setOn(opts.includes(status.wrapper)));
  }, [appid]);
  const usable = status.wrapper_installed && !!status.meikipop;
  return (
    <ToggleField
      label={running ? `▶ ${name}` : name}
      description={!usable ? "meikipop isn't installed" : on === null ? "..." : running ? "Running" : undefined}
      disabled={!usable || on === null}
      checked={!!on}
      onChange={async (v) => {
        const cur = await readLaunchOptions(appid); // fresh, in case they were edited meanwhile
        const next = v ? withWrapper(cur, status.wrapper) : withoutWrapper(cur, status.wrapper);
        setLaunchOptions(appid, next);
        setOn(v);
        let now = false;
        if ((await isRunning(appid)).game) now = v ? await startFor(appid) : await stopFor(appid);
        toaster.toast({ title: "meikipop", body: `${v ? "On" : "Off"} for ${name}${now ? (v ? " - starting now" : " - stopped") : ""}` });
      }}
    />
  );
}

// --- panel -------------------------------------------------------------------------------
function Content() {
  const [s, setS] = useState<Settings | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const running = Router.MainRunningApp;
  const runningId = running ? Number(running.appid) : null;
  const games = recentGames().filter((g) => g.appid !== runningId);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    getSettings().then(setS);
    getStatus().then(setStatus);
  }, []);

  const update = (key: keyof Settings, value: number | boolean) => {
    setS((old) => (old ? { ...old, [key]: value } : old));
    setSetting(key, value);
  };

  if (!s || !status) return null;

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ToggleField
            label="On"
            description="Pause or resume lookups"
            checked={s.enabled}
            onChange={(v) => update("enabled", v)}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Use with">
        {running && (
          <PanelSectionRow>
            <GameToggle appid={runningId!} name={running.display_name} status={status} running />
          </PanelSectionRow>
        )}
        {games.slice(0, showAll ? games.length : 6).map((g) => (
          <PanelSectionRow key={g.appid}>
            <GameToggle appid={g.appid} name={g.name} status={status} />
          </PanelSectionRow>
        ))}
        {!showAll && games.length > 6 && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => setShowAll(true)}>Show more</ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Popup">
        <PanelSectionRow>
          <SliderField label="Text size" value={s.font_size_definitions} min={12} max={40} step={1}
            showValue onChange={(v) => update("font_size_definitions", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Word size" value={s.font_size_header} min={14} max={48} step={1}
            showValue onChange={(v) => update("font_size_header", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Max width %" value={s.popup_max_width_percent} min={20} max={90} step={5}
            showValue onChange={(v) => update("popup_max_width_percent", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Max height %" value={s.popup_max_height_percent} min={20} max={90} step={5}
            showValue onChange={(v) => update("popup_max_height_percent", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <SliderField label="Opacity" value={s.background_opacity} min={60} max={255} step={5}
            showValue onChange={(v) => update("background_opacity", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Compact" checked={s.compact_mode} onChange={(v) => update("compact_mode", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="No key needed" description="Look up on hover, without holding the hotkey"
            checked={s.auto_scan_mode_lookups_without_hotkey}
            onChange={(v) => update("auto_scan_mode_lookups_without_hotkey", v)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => preview()}>Preview</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => resetSettings().then(() => getSettings().then(setS))}>
            Reset
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "meikipop",
  titleView: <div className={staticClasses.Title}>meikipop</div>,
  content: <Content />,
  icon: <FaBook />,
}));
