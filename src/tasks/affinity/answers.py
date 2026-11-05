"""The 亲密度谈心 answer bank (data/counseling.json, from souseha).

Leo 2026-10-21: below LV20 the right answer is picked from the bank; the
tool never fetches it (tools/fetch_souseha_counseling.py refreshes the file
in the repo).  Each costume has 15 questions with two answers worth 100 and
80 affinity; a costume souseha does not have yet gets the first answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from src.utils.chinese import to_simplified

BANK_FILE = Path(__file__).resolve().parent / "data" / "counseling.json"
# How alike an OCR'd answer and a bank answer must be (OCR drops or swaps a
# character now and then; the two answers of a question are never alike).
ANSWER_MIN_RATIO = 0.6
_DROP = re.compile(r"[\s，。、！？!?,.…·~～「」『』“”\"'：:（）()\-—]+")


def normalize(text: object) -> str:
    """Simplified, without spaces and punctuation, for comparing names and answers."""
    return _DROP.sub("", to_simplified(str(text or ""))).lower()


@dataclass(frozen=True)
class Costume:
    id: str
    character: str  # normalized simplified names
    costume: str
    # Per question: its answers' normalized texts (简体 and 繁體 forms) and value.
    questions: tuple[tuple[tuple[tuple[str, ...], int], ...], ...]
    # Per question: its prompt's normalized texts (简体 and 繁體 forms).
    prompts: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class Pick:
    index: int  # which of the read choices to press (0 = first)
    known: bool  # False: no bank answer matched, first choice by default
    why: str


def _texts(value: dict) -> tuple[str, ...]:
    return tuple(dict.fromkeys(t for t in (normalize(v) for v in value.values()) if t))


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[Costume, ...]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    costumes = []
    for entry in data.get("costumes") or []:
        questions = tuple(
            tuple(
                (_texts(answer.get("text") or {}), int(answer.get("exp") or 0))
                for answer in question.get("answers") or []
            )
            for question in entry.get("questions") or []
        )
        costumes.append(
            Costume(
                id=str(entry.get("id", "")),
                character=normalize(entry.get("character_zh_cn") or entry.get("character_zh_tw")),
                costume=normalize(entry.get("costume_zh_cn") or entry.get("costume_zh_tw")),
                questions=questions,
                prompts=tuple(
                    _texts(question.get("prompt") or {})
                    for question in entry.get("questions") or []
                ),
            )
        )
    return tuple(costumes)


def bank(path: Path = BANK_FILE) -> tuple[Costume, ...]:
    return _load(str(path))


def find_costume(costume_name: str, character_name: str = "", path: Path = BANK_FILE):
    """The bank entry for a costume as the game names it, or None.

    The costume name alone is unique so far; the character name settles a
    misread costume name."""
    wanted = normalize(costume_name)
    who = normalize(character_name)
    if not wanted:
        return None
    best, best_ratio = None, 0.0
    for costume in bank(path):
        ratio = SequenceMatcher(None, wanted, costume.costume).ratio()
        if who and costume.character:
            ratio = (ratio * 2 + SequenceMatcher(None, who, costume.character).ratio()) / 3
        if ratio > best_ratio:
            best, best_ratio = costume, ratio
    return best if best_ratio >= 0.75 else None


def short_answers(costume: Costume | None) -> frozenset:
    """The costume's answers short enough to look like a stray glyph (one or
    two characters once normalized), so a short centred line is only taken
    for a button when it is one of them."""
    if costume is None:
        return frozenset()
    return frozenset(
        text
        for question in costume.questions
        for texts, _exp in question
        for text in texts
        if 0 < len(text) < 3
    )


def _similar(read: str, texts: tuple[str, ...]) -> float:
    if not read:
        return 0.0
    return max((SequenceMatcher(None, read, text).ratio() for text in texts), default=0.0)


def _prompt_on_screen(prompts: tuple[str, ...], screen: str) -> float:
    """How much of a question's prompt the screen text holds (0..1)."""
    best = 0.0
    for prompt in prompts:
        if prompt and screen:
            match = SequenceMatcher(None, prompt, screen, autojunk=False).find_longest_match()
            best = max(best, match.size / len(prompt))
    return best


def pick_answer(choices: list[str], costume: Costume | None, screen_text: str = "") -> Pick:
    """Which read choice gives the most affinity.

    Every question of the costume is tried: the answers alone tell the
    questions apart, except where two questions share their answers with
    the values swapped (暗黑圣女 6 and 7: 「有。」/「没有。」); then the
    question whose prompt the screen shows (``screen_text``) wins.  The read
    choices are matched to that question's answers; the best-valued one is
    pressed.  Nothing matching well enough: the first choice, as at LV20."""
    read = [normalize(choice) for choice in choices]
    if len(read) < 2:
        return Pick(0, False, "没读到两个选项")
    pools = [costume] if costume is not None else []
    if costume is None:
        pools = list(bank())  # unknown costume name: any costume's answers
    screen = normalize(screen_text)
    best = None  # (score, prompt on screen, slot, exp, answers)
    for entry in pools:
        for number, answers in enumerate(entry.questions):
            prompts = entry.prompts[number] if number < len(entry.prompts) else ()
            shown = _prompt_on_screen(prompts, screen)
            for slot, text in enumerate(read):
                for texts, exp in answers:
                    score = _similar(text, texts)
                    if score >= ANSWER_MIN_RATIO and (
                        best is None or (score, shown) > (best[0], best[1])
                    ):
                        best = (score, shown, slot, exp, answers)
    if best is None:
        return Pick(0, False, "题库里没有这题，选第一个")
    _score, _shown, slot, exp, answers = best
    top = max(value for _texts_, value in answers)
    if exp >= top:
        return Pick(slot, True, f"题库答案（{exp}）")
    # The matched choice is the lower one: press the other choice.
    others = [i for i in range(len(read)) if i != slot]
    # With more than two read lines pick the one most like the top answer.
    top_texts = next(texts for texts, value in answers if value == top)
    other = max(others, key=lambda i: _similar(read[i], top_texts))
    return Pick(other, True, f"题库答案（{top}）")
