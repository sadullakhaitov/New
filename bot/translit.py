"""O'zbek lotin yozuvidan kirill yozuviga transliteratsiya (admin qo'shgan taom nomlari uchun)."""
from __future__ import annotations

import re

_APOSTROPHES = "'‘’ʻʼ`"
_DIGRAPHS = {
    "o'": "ў", "g'": "ғ", "sh": "ш", "ch": "ч",
    "yo": "ё", "yu": "ю", "ya": "я", "ye": "е",
}
_SINGLE = {
    "a": "а", "b": "б", "d": "д", "f": "ф", "g": "г", "h": "ҳ", "i": "и",
    "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "х",
    "y": "й", "z": "з", "c": "к", "w": "в",
}
_VOWELS = set("aeiou")
_WORD = re.compile(r"[A-Za-z" + re.escape(_APOSTROPHES) + r"]+")


def _match_case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def _word(word: str) -> str:
    # Qisqartmalar (KFC, XL) o'zgarishsiz qoladi.
    letters = [c for c in word if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) <= 4:
        return word
    norm = "".join("'" if c in _APOSTROPHES else c for c in word)
    out = []
    i = 0
    while i < len(norm):
        pair = norm[i:i + 2]
        low = pair.lower()
        if low in _DIGRAPHS:
            out.append(_match_case(pair, _DIGRAPHS[low]))
            i += 2
            continue
        ch = norm[i]
        low = ch.lower()
        if low == "e":
            prev = norm[i - 1].lower() if i else ""
            cyr = "э" if (i == 0 or prev in _VOWELS) else "е"
            out.append(_match_case(ch, cyr))
        elif low in _SINGLE:
            out.append(_match_case(ch, _SINGLE[low]))
        elif ch == "'":
            out.append("ъ" if 0 < i < len(norm) - 1 else "")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def latin_to_cyrillic(text: str) -> str:
    return _WORD.sub(lambda m: _word(m.group(0)), text or "")
