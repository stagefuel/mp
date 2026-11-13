import json
import os

import pytest

import meikipop
from meikipop.dictionary.deconjugator import Deconjugator, Form


@pytest.fixture(scope="module")
def deconjugator():
    path = os.path.join(os.path.dirname(meikipop.__file__), "scripts", "deconjugator.json")
    with open(path, encoding="utf-8") as f:
        return Deconjugator(json.load(f))


def texts(forms):
    return {f.text for f in forms}


@pytest.mark.parametrize("conjugated, dictionary_form", [
    ("食べた", "食べる"),
    ("食べている", "食べる"),
    ("食べませんでした", "食べる"),
    ("書いた", "書く"),
    ("読んで", "読む"),
    ("高くない", "高い"),
    ("行かなかった", "行く"),
])
def test_finds_dictionary_form(deconjugator, conjugated, dictionary_form):
    assert dictionary_form in texts(deconjugator.deconjugate(conjugated))


def test_original_text_is_always_included(deconjugator):
    assert Form(text="猫") in deconjugator.deconjugate("猫")
    assert Form(text="食べた") in deconjugator.deconjugate(" 食べた ")


def test_empty_input(deconjugator):
    assert deconjugator.deconjugate("") == set()
    assert deconjugator.deconjugate("   ") == set()


def test_malformed_rules_are_ignored():
    d = Deconjugator(["comment", {"type": "stdrule"}, {"type": "stdrule", "dec_end": "る"}])
    assert texts(d.deconjugate("食べた")) == {"食べた"}
