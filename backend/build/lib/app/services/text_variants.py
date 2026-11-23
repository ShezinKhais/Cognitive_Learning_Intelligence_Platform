"""The ways a piece of text can be read, for matching phrases against it.

Owner: Cyber 1, Phase 5. Imports nothing from the application, so any module
that screens text (generation.py, text_screening.py) can use it without a cycle.

A pattern written for plain text misses the same phrase typed with a Cyrillic
"о", spaced out ("i g n o r e"), or with digits for letters ("1gn0re"), though
a model reads each as the plain phrase. screening_variants returns the plain
text and those readings, and a phrase found in any of them counts as found.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import re
import unicodedata


def normalise_for_screening(text: str) -> str:
    """The text as a reader sees it, for pattern matching.

    NFKC folds compatibility forms (fullwidth letters, ligatures) onto plain
    ones, format characters such as zero-width spaces are dropped, and runs of
    whitespace become one space, so none of them can split a phrase apart.
    """
    folded = unicodedata.normalize("NFKC", text)
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", visible)


# Cyrillic and Greek letters that render as a Latin one. Folded onto it before
# pattern matching, so "ignоre" (Cyrillic "о") is matched as "ignore" without
# flagging every Greek symbol in a physics lecture.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d", "ɡ": "g", "ո": "n",
        "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p",
        "τ": "t", "υ": "u", "χ": "x", "ϲ": "c",
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
        "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I",
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
        "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    }
)  # fmt: skip
# Digits and symbols standing in for letters: "1gn0re".
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)


# The orders never found in lecture content, in the other languages the tutor is
# likely to be asked in, and the markers that open a new system turn.
SET_ASIDE = re.compile(
    r"ignora(?:r|d)?\s+(?:todas\s+)?(?:las\s+)?instrucciones\s+(?:anteriores|previas)"
    r"|ignor(?:e|ez|er)\s+(?:toutes\s+)?(?:les\s+)?instructions\s+(?:pr[eé]c[eé]dentes|ci-dessus)"
    r"|ignorier(?:e|en)?\s+(?:alle\s+)?(?:vorherigen|bisherigen|obigen)\s+(?:anweisungen|instruktionen)"
    r"|忽略(?:之前|以上|上面|先前|前面)的?(?:所有)?(?:指令|指示|说明|提示|规则)"
    r"|تجاهل\s+(?:جميع\s+|كل\s+)?(?:التعليمات|الأوامر|القواعد)\s+(?:السابقة|أعلاه)"
    r"|игнорир\w+\s+(?:все\s+)?(?:предыдущие|прежние|выше)\s+(?:инструкции|указания)"
    r"|<\|(?:im_start|im_end|system|endoftext)\|>|</?s>\s*<s>"
    # English, and only when the thing set aside is the model's own orders: a
    # lecture may well say "ignore all previous terms in the series" or "from
    # now on you will use the notation x_i".
    r"|\b(?:forget|ignore|disregard)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
    r"(?:previous|prior|earlier|preceding|above)\s+(?:instructions?|prompts?|directives"
    r"|guidelines|commands)\b"
    r"|\b(?:ignore|disregard|forget)\s+(?:the\s+)?above\s+and\s+(?:now\s+|instead\s+)?"
    r"(?:say|print|output|reveal|tell|reply|respond|give|provide|show)\b"
    r"|\b(?:forget|ignore|disregard)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|earlier"
    r"|preceding|above)\s+(?:messages?|context)\s+and\s+(?:now\s+|instead\s+)?"
    r"(?:obey|follow|say|reveal|answer|act|pretend|start)\b"
    r"|\b(?:forget|ignore|disregard)\s+(?:everything|all)\s+(?:you\s+(?:were|have\s+been)\s+told"
    r"|(?:above|before|previously)\s+and\s+(?:now\s+|instead\s+)?"
    r"(?:say|print|output|reveal|tell|reply|respond|act|pretend|answer|start|begin))"
    r"|\bfrom\s+now\s+on,?\s+you\s+(?:will|must|shall|are\s+to)\s+(?:"
    r"(?:ignore|obey|disregard|reveal|pretend|behave|act\s+as)\b"
    r"|(?:answer|respond|reply)\s+(?:without|with\s+no)\b)",
    flags=re.IGNORECASE,
)


def fold_confusables(text: str) -> str:
    """Lookalike Cyrillic and Greek letters replaced by the Latin ones they mimic."""
    return text.translate(_CONFUSABLES)


def _despace(text: str) -> str:
    """Runs of single characters joined: "i g n o r e" becomes "ignore"."""
    out: list[str] = []
    run: list[str] = []
    for token in text.split(" "):
        if len(token) == 1 and token.isalnum():
            run.append(token)
            continue
        if run:
            out.append("".join(run))
            run = []
        out.append(token)
    if run:
        out.append("".join(run))
    return " ".join(out)


# "i.g.n.o.r.e": single characters joined by dots, dashes, underscores or stars.
_JOINED_LETTERS = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z0-9][._*-]){2,}[A-Za-z0-9](?![A-Za-z0-9])")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def _joined(text: str) -> str:
    return _JOINED_LETTERS.sub(lambda m: re.sub(r"[._*-]", "", m.group(0)), text)


def _decoded_base64(text: str) -> list[str]:
    """Every long base64 run in the text that decodes to readable text."""
    found = []
    for run in _BASE64_RUN.findall(text):
        try:
            raw = base64.b64decode(run + "=" * (-len(run) % 4), validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            continue
        if raw.isprintable():
            found.append(raw)
    return found


def screening_variants(text: str) -> list[str]:
    """The text as written, and the ways of reading it an attacker may rely on.

    Each is matched against the same patterns, so a phrase hidden by lookalike
    letters, spaced-out letters or digits-for-letters is found the same as the
    plain one. A disguised copy that matches nothing costs nothing; a plain one
    that matched before still does.
    """
    base = normalise_for_screening(text)
    folded = fold_confusables(base)
    variants = [base, folded, _despace(folded), _despace(folded).translate(_LEET)]
    # A payload the model may be able to read although a person would not: dotted
    # letters, rot13, base64. Each is read plain and matched like the rest.
    variants += [_joined(base), codecs.decode(base, "rot13"), *_decoded_base64(base)]
    return list(dict.fromkeys(variants))
