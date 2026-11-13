from meikipop.utils.japanese import JAPANESE_REGEX, KANJI_REGEX, hira_to_kata, kata_to_hira


def test_kana_conversion_round_trip():
    assert kata_to_hira("タベル") == "たべる"
    assert hira_to_kata("たべる") == "タベル"
    assert kata_to_hira(hira_to_kata("ぁゖ")) == "ぁゖ"


def test_kana_conversion_leaves_other_text_alone():
    assert kata_to_hira("食べるABC ー") == "食べるABC ー"
    assert hira_to_kata("漢字abc") == "漢字abc"


def test_katakana_iteration_marks():
    assert kata_to_hira("ヽヾ") == "ゝゞ"


def test_character_classes():
    assert KANJI_REGEX.match("猫") and not KANJI_REGEX.match("ね")
    assert JAPANESE_REGEX.search("abc ね") and JAPANESE_REGEX.search("ネ") and JAPANESE_REGEX.search("猫")
    assert not JAPANESE_REGEX.search("hello, world 123")
