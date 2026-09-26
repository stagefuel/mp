# meikipop/anki/ankiconnect.py
import html
from functools import partial
import logging
from typing import List, Optional

import requests

from meikipop.config.config import config
from meikipop.dictionary import freqlist
from meikipop.dictionary.lookup import DictionaryEntry, KanjiEntry

logger = logging.getLogger(__name__)

escape = partial(html.escape, quote=False)  # like JL: only <, > and & are escaped

# what can be put into a note field; keys are stored in config.anki_fields
FIELD_CONTENT_TYPES = {
    'nothing': 'Nothing',
    'word': 'Word',
    'reading': 'Reading',
    'definitions': 'Definitions',
    'first_definition': 'First Definition',
    'sentence': 'Sentence',
    'pos': 'Part of Speech',
    'frequency': 'Frequency',
}

SENTENCE_TERMINATORS = '。！？!?…\n'


class AnkiError(Exception):
    pass


class DuplicateNoteError(AnkiError):
    pass


def invoke(action, **params):
    try:
        response = requests.post(config.anki_connect_url,
                                 json={'action': action, 'version': 6, 'params': params}, timeout=5)
        response.raise_for_status()
        reply = response.json()
    except requests.RequestException as e:
        raise AnkiError(f"Can't reach AnkiConnect at {config.anki_connect_url} - is Anki running?") from e
    if reply.get('error'):
        if 'duplicate' in reply['error']:
            raise DuplicateNoteError(reply['error'])
        raise AnkiError(reply['error'])
    return reply.get('result')


def parse_field_map(field_map: str) -> dict:
    """'Word=word;Reading=reading' -> {'Word': 'word', 'Reading': 'reading'}"""
    fields = {}
    for pair in field_map.split(';'):
        if '=' in pair:
            name, content = pair.split('=', 1)
            if name.strip():
                fields[name.strip()] = content.strip()
    return fields


def format_field_map(fields: dict) -> str:
    return ';'.join(f"{name}={content}" for name, content in fields.items() if content != 'nothing')


def extract_sentence(text: Optional[str], index: int) -> str:
    """The sentence of text that contains index, terminator included."""
    if not text:
        return ''
    start = index
    while start > 0 and text[start - 1] not in SENTENCE_TERMINATORS:
        start -= 1
    end = index
    while end < len(text) and text[end] not in SENTENCE_TERMINATORS:
        end += 1
    while end < len(text) and text[end] in SENTENCE_TERMINATORS and text[end] != '\n':
        end += 1
    return text[start:end].strip()


def _format_sense(sense: dict, number: Optional[int]) -> str:
    parts = [f"({number})"] if number else []
    if sense.get('pos'):
        parts.append(f"({', '.join(sense['pos'])})")
    if sense.get('tags'):
        parts.append(f"({', '.join(sense['tags'])})")
    parts.append(escape('; '.join(sense.get('glosses', []))))
    return ' '.join(parts)


def field_values(entry, sentence: str) -> dict:
    """All field content types for one popup entry, formatted like JL's cards."""
    if isinstance(entry, KanjiEntry):
        return {
            'word': entry.character,
            'reading': '、'.join(entry.readings),
            'definitions': escape('; '.join(entry.meanings)),
            'first_definition': escape(entry.meanings[0]) if entry.meanings else '',
            'sentence': escape(sentence),
            'pos': '',
            'frequency': '',
            'nothing': '',
        }
    senses = entry.senses
    if len(senses) == 1:
        definitions = _format_sense(senses[0], None)
    else:
        definitions = '<br/>'.join(_format_sense(s, i + 1) for i, s in enumerate(senses))
    pos = []
    for s in senses:
        pos.extend(p for p in s.get('pos', []) if p not in pos)
    return {
        'word': entry.written_form,
        'reading': entry.reading,
        'definitions': definitions,
        'first_definition': _format_sense(senses[0], None) if senses else '',
        'sentence': escape(sentence),
        'pos': ', '.join(pos),
        'frequency': str(freqlist.rank(entry) or ''),
        'nothing': '',
    }


def add_note(entry, sentence: str = '') -> int:
    """Adds entry as a note per the Anki settings. Returns the note id, raises AnkiError."""
    values = field_values(entry, sentence)
    fields = {name: values.get(content, '') for name, content in parse_field_map(config.anki_fields).items()}
    note = {
        'deckName': config.anki_deck,
        'modelName': config.anki_note_type,
        'fields': fields,
        'tags': config.anki_tags.split(),
        'options': {'allowDuplicate': config.anki_allow_duplicates},
    }
    note_id = invoke('addNote', note=note)
    logger.info(f"Anki: added '{values['word']}' to deck '{config.anki_deck}' (note {note_id})")
    return note_id


def deck_names() -> List[str]:
    return invoke('deckNames')


def model_names() -> List[str]:
    return invoke('modelNames')


def model_field_names(model_name: str) -> List[str]:
    return invoke('modelFieldNames', modelName=model_name)
