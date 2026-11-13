# meikipop/utils/japanese.py
"""Character classes and kana conversion shared by the ocr providers, the lookup and the texthooker feed."""
import re

DEFAULT_FREQ = 999_999  # frequency rank of a word that is in no frequency list

KANJI_REGEX = re.compile(r'[一-龯]')
JAPANESE_REGEX = re.compile(r'[぀-ゟ゠-ヿ一-龯]')  # hiragana, katakana, kanji


def hira_to_kata(text: str) -> str:
    return ''.join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in text)


def kata_to_hira(text: str) -> str:
    res = []
    for c in text:
        code = ord(c)
        if 0x30A1 <= code <= 0x30F6:
            res.append(chr(code - 0x60))
        elif code == 0x30FD:
            res.append('ゝ')  # ヽ → ゝ
        elif code == 0x30FE:
            res.append('ゞ')  # ヾ → ゞ
        else:
            res.append(c)
    return ''.join(res)
