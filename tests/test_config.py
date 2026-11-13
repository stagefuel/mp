import configparser
import os

import pytest

import meikipop
from meikipop.config import config as config_module
from meikipop.config.config import APP_VERSION, Config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = str(tmp_path / "sub" / "config.ini")
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    c = object.__new__(Config)  # a fresh instance instead of the process-wide singleton
    c._load()
    return c, path


def test_defaults_without_a_file(cfg):
    c, _ = cfg
    for settings in Config._SCHEMA.values():
        for key, default in settings.items():
            assert getattr(c, key) == default


def test_save_and_load_round_trip(cfg):
    c, path = cfg
    c.hotkey = "ctrl"
    c.auto_scan_mode = False
    c.max_lookup_length = 12
    c.auto_scan_interval_seconds = 1.5
    c.save()

    again = object.__new__(Config)
    again._load()
    assert (again.hotkey, again.auto_scan_mode, again.max_lookup_length, again.auto_scan_interval_seconds) \
        == ("ctrl", False, 12, 1.5)
    for settings in Config._SCHEMA.values():
        for key, default in settings.items():
            assert type(getattr(again, key)) is type(default), key


def test_save_leaves_no_temp_file_and_replaces_the_old_one(cfg):
    c, path = cfg
    c.save()
    c.hotkey = "alt"
    c.save()
    assert os.listdir(os.path.dirname(path)) == ["config.ini"]
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    assert parser.get("Settings", "hotkey") == "alt"


def test_failed_save_keeps_the_previous_file(cfg, monkeypatch):
    c, path = cfg
    c.save()
    before = open(path, encoding="utf-8").read()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(configparser.ConfigParser, "write", boom)
    with pytest.raises(OSError):
        c.save()
    assert open(path, encoding="utf-8").read() == before


def test_unknown_keys_and_missing_keys_are_tolerated(cfg):
    c, path = cfg
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Settings]\nhotkey = ctrl\nno_such_key = 1\n")
    c._load()
    assert c.hotkey == "ctrl"
    assert c.max_lookup_length == Config._SCHEMA["Settings"]["max_lookup_length"]


def test_versions_agree():
    assert APP_VERSION.startswith(meikipop.__version__)
