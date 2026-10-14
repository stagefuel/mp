# meikipop/utils/updater.py
"""In-app updates from this fork's GitHub releases (stagefuel/mp).

Which builds update themselves:
  - the windows exe and the linux binary: download the new file next to the running one, then a small script swaps
    it in once meikipop has exited and starts the new version
  - the flatpak: download the new bundle, then the host's flatpak reinstalls it after meikipop has exited
  - running from source: only told that a new version exists

Releases are picked by this build's own version: linux preview builds also look at pre-releases, everything else
only at normal releases. A release without a file for this kind of install is skipped."""
import configparser
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from meikipop.config.config import APP_VERSION, IS_LINUX, IS_WINDOWS
from meikipop.utils.paths import paths

logger = logging.getLogger(__name__)

REPO = "stagefuel/mp"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
FLATPAK_APP_ID = "io.github.stagefuel.meikipop"

_VERSION_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:-fork\.(\d+))?(?:-linux-preview\.(\d+))?$')

# the file each kind of install updates from
_ASSET_SUFFIX = {
    'windows': '-windows-x64.exe',
    'linux': '-linux-x64',
    'flatpak': '-linux-x64.flatpak',
}


def version_key(version):
    """(major, minor, patch, fork, preview) for comparing, or None for a version this fork never used."""
    m = _VERSION_RE.match(version.strip())
    return tuple(int(g or 0) for g in m.groups()) if m else None


def is_preview(version):
    return '-linux-preview.' in version


def install_kind():
    if os.environ.get('FLATPAK_ID') or os.path.exists('/.flatpak-info'):
        return 'flatpak'
    if getattr(sys, 'frozen', False):
        if IS_WINDOWS:
            return 'windows'
        if IS_LINUX:
            return 'linux'
    return 'source'


def can_self_update(kind=None):
    return (kind or install_kind()) in _ASSET_SUFFIX


@dataclass
class Update:
    version: str
    notes: str
    page_url: str
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None
    size: int = 0
    sha256: Optional[str] = None


def find_update(current=APP_VERSION, kind=None, timeout=15):
    """The newest release this install can move to, or None if it's up to date. Raises on network errors."""
    kind = kind or install_kind()
    current_key = version_key(current)
    if current_key is None:
        logger.info(f"Updater: version '{current}' isn't a release version, not checking.")
        return None
    response = requests.get(RELEASES_API, timeout=timeout, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': f'meikipop/{current}'})
    response.raise_for_status()

    best = None
    for release in response.json():
        tag = release.get('tag_name', '')
        key = version_key(tag)
        if release.get('draft') or key is None or key <= current_key:
            continue
        if release.get('prerelease') and not is_preview(current):
            continue
        asset = None
        suffix = _ASSET_SUFFIX.get(kind)
        if suffix:
            asset = next((a for a in release.get('assets', []) if a['name'].endswith(suffix)), None)
            if asset is None:
                continue  # that release has no build of this kind
        if best is None or key > best[0]:
            best = (key, release, asset)

    if best is None:
        return None
    _, release, asset = best
    update = Update(version=release['tag_name'], notes=(release.get('body') or '').strip(),
                    page_url=release.get('html_url') or RELEASES_PAGE)
    if asset:
        digest = asset.get('digest') or ''
        update.asset_name = asset['name']
        update.asset_url = asset['browser_download_url']
        update.size = asset.get('size', 0)
        update.sha256 = digest[len('sha256:'):] if digest.startswith('sha256:') else None
    return update


def download_path(update, kind=None):
    """Where the new file goes: next to the running program (so the swap is a rename on the same drive), or the
    cache dir for the flatpak (the host's flatpak can read it there)."""
    if (kind or install_kind()) == 'flatpak':
        os.makedirs(paths.cache_dir, exist_ok=True)
        return os.path.join(paths.cache_dir, update.asset_name)
    return sys.executable + '.new'


def download(update, dest, progress: Callable[[int, int], None] = None, cancelled: Callable[[], bool] = None):
    """Download the release file to `dest`, checking its size and sha256. Returns False if cancelled."""
    part = dest + '.part'
    sha = hashlib.sha256()
    done = 0
    try:
        with requests.get(update.asset_url, stream=True, timeout=30,
                          headers={'User-Agent': f'meikipop/{APP_VERSION}'}) as response:
            response.raise_for_status()
            total = update.size or int(response.headers.get('Content-Length') or 0)
            with open(part, 'wb') as f:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancelled and cancelled():
                        return False
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if update.size and done != update.size:
            raise IOError(f"download incomplete ({done} of {update.size} bytes)")
        if update.sha256 and sha.hexdigest().lower() != update.sha256.lower():
            raise IOError("downloaded file doesn't match the release's checksum")
        os.replace(part, dest)
        return True
    finally:
        if os.path.exists(part):
            os.remove(part)


def target_exe_path(new_version):
    """The updated program's path: the same file, unless its name carries the old version (as release downloads
    do), in which case it is renamed to the new one."""
    current = sys.executable
    folder, name = os.path.split(current)
    if APP_VERSION in name:
        return os.path.join(folder, name.replace(APP_VERSION, new_version))
    return current


def _waited_pids():
    """meikipop's process, plus pyinstaller's onefile bootloader that started it - both hold the exe open."""
    pids = [os.getpid()]
    meipass = getattr(sys, '_MEIPASS', '')
    if os.path.basename(os.path.normpath(meipass)).startswith('_MEI'):
        pids.append(os.getppid())
    return pids


def _clean_env():
    # the new version's bootloader must not reuse this process's unpacked files
    env = dict(os.environ)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def windows_swap_script(current_exe, new_exe, target_exe, pids):
    """A script that waits for meikipop to exit, moves the new exe into place (removing the old one if the name
    changed) and starts it; if the swap keeps failing it starts the old exe again. Logs next to itself."""
    q = lambda s: s.replace('"', '')
    renamed = os.path.normcase(os.path.abspath(target_exe)) != os.path.normcase(os.path.abspath(current_exe))
    lines = [
        '@echo off',
        'chcp 65001 >nul',
        'setlocal',
        f'set "CUR={q(current_exe)}"',
        f'set "NEW={q(new_exe)}"',
        f'set "TARGET={q(target_exe)}"',
        'set "LOG=%~dpn0.log"',
        f'echo %DATE% %TIME% waiting for meikipop (pid {", ".join(map(str, pids))}) to close>"%LOG%"',
        'set /a WAITED=0',
        ':wait',
        'if %WAITED% GEQ 120 goto closed',
        *[f'tasklist /FI "PID eq {p}" /NH 2>nul | find " {p} " >nul && goto waitmore' for p in pids],
        'goto closed',
        ':waitmore',
        'set /a WAITED+=1',
        'ping -n 2 127.0.0.1 >nul',
        'goto wait',
        ':closed',
        'echo %TIME% closed, replacing the program>>"%LOG%"',
        'set /a TRIES=0',
        ':swap',
        'move /y "%NEW%" "%TARGET%" >>"%LOG%" 2>&1 && goto swapped',
        'set /a TRIES+=1',
        'if %TRIES% GEQ 30 goto failed',
        'ping -n 2 127.0.0.1 >nul',
        'goto swap',
        ':swapped',
    ]
    if renamed:
        lines += [
            'echo %TIME% removing the old version>>"%LOG%"',
            'set /a TRIES=0',
            ':delold',
            'del /f /q "%CUR%" >>"%LOG%" 2>&1',
            'if not exist "%CUR%" goto start',
            'set /a TRIES+=1',
            'if %TRIES% GEQ 15 goto start',
            'ping -n 2 127.0.0.1 >nul',
            'goto delold',
        ]
    lines += [
        'goto start',
        ':failed',
        'echo %TIME% could not replace the program; starting the old one>>"%LOG%"',
        'set "TARGET=%CUR%"',
        ':start',
        'echo %TIME% starting meikipop>>"%LOG%"',
        'start "" "%TARGET%"',
        '(goto) 2>nul & del "%~f0"',
        '',
    ]
    return '\r\n'.join(lines)


def _flatpak_installation():
    """'--user' or '--system', whichever this flatpak was installed into."""
    info = configparser.ConfigParser()
    try:
        info.read('/.flatpak-info')
        app_path = info.get('Instance', 'app-path', fallback='')
    except configparser.Error:
        app_path = ''
    return '--system' if app_path.startswith('/var/lib/flatpak') else '--user'


def apply(update, downloaded, kind=None):
    """Hand the downloaded update to a helper that outlives meikipop, then the caller must quit the app at once.
    Returns the path meikipop will be started from afterwards (for messages)."""
    kind = kind or install_kind()
    pids = _waited_pids()

    if kind == 'windows':
        target = target_exe_path(update.version)
        script = os.path.join(tempfile.gettempdir(), f'meikipop-update-{os.getpid()}.cmd')
        with open(script, 'w', encoding='utf-8', newline='') as f:
            f.write(windows_swap_script(sys.executable, downloaded, target, pids))
        # the script needs its own console: started as a plain child it dies with meikipop, and started detached
        # without one its tasklist/ping calls hang (found in vn-shelf's updater)
        comspec = os.environ.get('ComSpec', 'cmd.exe')
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        subprocess.Popen(f'"{comspec}" /d /c start "" /min "{comspec}" /d /c "{script}"', env=_clean_env(),
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                         startupinfo=startupinfo, close_fds=True)
        logger.info(f"Updater: swap script {script} started")
        return target

    if kind == 'linux':
        # a running binary can be replaced on linux: the old process keeps its open copy
        current = sys.executable
        target = target_exe_path(update.version)
        os.chmod(downloaded, 0o755)
        os.replace(downloaded, target)
        if target != current:
            try:
                os.remove(current)
            except OSError as e:
                logger.warning(f"Updater: couldn't remove the old binary: {e}")
        waits = ' || '.join(f'kill -0 {p} 2>/dev/null' for p in pids)
        subprocess.Popen(['/bin/sh', '-c', f'n=0; while {{ {waits}; }} && [ $n -lt 600 ]; do sleep 0.2; '
                                           f'n=$((n+1)); done; exec "$0"', target],
                         env=_clean_env(), start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return target

    if kind == 'flatpak':
        # runs on the host (needs --talk-name=org.freedesktop.Flatpak): wait until this app has stopped, reinstall
        # from the bundle, start it again. the bundle is in the app's cache dir, which the host sees at the same path
        installation = _flatpak_installation()
        host_script = (
            f'n=0; while flatpak ps --columns=application 2>/dev/null | grep -qx {FLATPAK_APP_ID} && [ $n -lt 300 ]; '
            f'do sleep 0.2; n=$((n+1)); done; '
            f'flatpak install {installation} -y --noninteractive --reinstall --bundle "$0" '
            f'&& rm -f "$0"; exec flatpak run {FLATPAK_APP_ID}')
        subprocess.Popen(['flatpak-spawn', '--host', '/bin/sh', '-c', host_script, downloaded],
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return FLATPAK_APP_ID

    raise RuntimeError(f"this install ({kind}) can't update itself")
