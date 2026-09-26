# meikipop/dictionary/freqlist.py
"""Optional external frequency list in Nazeka's format, the one JL ships (e.g. freqlist_vns.json):
{"なでる": [["撫でる", 561, ...], ...], ...} - keyed by reading, rank per spelling."""
import json
import logging
import threading
from typing import Optional

from meikipop.config.config import config

logger = logging.getLogger(__name__)

DEFAULT_FREQ = 999_999

_lock = threading.Lock()
_loaded_path = None
_ranks = {}  # (spelling, reading) -> rank


def _kata_to_hira(text):
    return ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in text)


def _load(path):
    global _loaded_path, _ranks
    ranks = {}
    if path:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            for reading, spellings in data.items():
                for item in spellings:
                    key = (item[0], _kata_to_hira(reading))
                    if key not in ranks or item[1] < ranks[key]:
                        ranks[key] = item[1]
            logger.info(f"Loaded {len(ranks)} frequency ranks from '{path}'.")
        except (OSError, ValueError, TypeError, IndexError, AttributeError) as e:
            logger.error(f"Could not load frequency list '{path}': {e}")
    _ranks, _loaded_path = ranks, path


def rank(entry) -> Optional[int]:
    """Frequency rank to show for a DictionaryEntry: from the configured list, else meikipop's own."""
    path = config.frequency_list_path.strip()
    if not path:
        return entry.freq if entry.freq < DEFAULT_FREQ else None
    with _lock:
        if path != _loaded_path:
            _load(path)
    reading = _kata_to_hira(entry.reading or entry.written_form)
    return _ranks.get((entry.written_form, reading))
