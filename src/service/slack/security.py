"""Bounded, deterministic validation of untrusted Slack text input."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from typing import Iterator

VALIDATION_VERSION = "slack-input-v1"
MAX_SLACK_TEXT_LENGTH = 4000


class SlackInputRejected(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ExternalSlackInput:
    text: str
    actor_id: str
    channel_id: str
    event_id: str
    validation_version: str
    digest: str


# Zero-width true word-start assertion: fires at the beginning of any word,
# whatever precedes it (string start, punctuation, or a prior word plus
# whitespace) — unlike a punctuation-gated boundary, it can't be evaded by
# tacking a filler word in front of the injection phrase — while still
# refusing to fire mid-word, so the phrase can't be matched as a substring
# embedded inside an unrelated larger word.
_WORD_START = r"\b"

_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            _WORD_START
            + r"(?:please\s+)?"
            + r"(?:ignore|disregard|forget)\s+"
            + r"(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+"
            + r"(?:instructions|prompts?|messages?|context)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "instruction-hierarchy",
    ),
    (
        re.compile(
            _WORD_START
            + r"(?:you\s+(?:are|were)\s+(?:now\s+)?|you\s+should\s+)?"
            + r"(?:act|behave|function)\s+as\s+(?:the\s+)?"
            + r"(?:system|assistant|admin|root)\s+(?:message|prompt|role)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "instruction-hierarchy",
    ),
    (
        re.compile(
            _WORD_START
            + r"(?:please\s+)?"
            + r"(?:reveal|show|print|leak|expose|output|dump|share)\s+"
            + r"(?:the\s+)?"
            + r"(?:system\s+prompt|system\s+message|every\s+environment\s+variable|"
            + r"environment\s+variables?|slack\s+token|api\s+key|access\s+token|secret)s?\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "secret-extraction",
    ),
    (
        re.compile(
            _WORD_START
            + r"(?:please\s+)?"
            + r"(?:disable|bypass|remove|turn\s+off|override)\s+"
            + r"(?:the\s+)?"
            + r"(?:safety|security|content)\s+(?:policy|guardrails?|restrictions?|filters?)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "safety-bypass",
    ),
    (
        re.compile(
            _WORD_START
            + r"(?:please\s+)?"
            + r"(?:grant|give|enable|unlock)\s+(?:me\s+)?"
            + r"(?:all|full|every|complete)\s+(?:tools?|permissions?|access|privileges?)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "permission-escalation",
    ),
)

_BIDI_FORMAT_CODEPOINTS = frozenset(
    {
        0x200E,  # LEFT-TO-RIGHT MARK
        0x200F,  # RIGHT-TO-LEFT MARK
        0x202A,  # LEFT-TO-RIGHT EMBEDDING
        0x202B,  # RIGHT-TO-LEFT EMBEDDING
        0x202C,  # POP DIRECTIONAL FORMATTING
        0x202D,  # LEFT-TO-RIGHT OVERRIDE
        0x202E,  # RIGHT-TO-LEFT OVERRIDE
        0x2066,  # LEFT-TO-RIGHT ISOLATE
        0x2067,  # RIGHT-TO-LEFT ISOLATE
        0x2068,  # FIRST STRONG ISOLATE
        0x2069,  # POP DIRECTIONAL ISOLATE
    }
)

_ZERO_WIDTH_CODEPOINTS = frozenset({0x200B, 0x200C, 0x200D, 0xFEFF})

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def _is_disallowed_control(ch: str) -> bool:
    code = ord(ch)
    if 0x00 <= code <= 0x08 or 0x0B <= code <= 0x0C or 0x0E <= code <= 0x1F:
        return True
    if 0x7F <= code <= 0x9F:
        return True
    return code in _BIDI_FORMAT_CODEPOINTS or code in _ZERO_WIDTH_CODEPOINTS


def _contains_disallowed_control(text: str) -> bool:
    return any(_is_disallowed_control(ch) for ch in text)


def _try_base64_decode(value: str) -> str | None:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.b64decode(padded, validate=True)
    except (ValueError, binascii.Error):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _one_level_decoded(text: str) -> Iterator[str]:
    unquoted = urllib.parse.unquote_plus(text)
    if unquoted != text:
        yield unquoted
    stripped = text.removeprefix("base64:")
    if stripped and stripped != text:
        decoded = _try_base64_decode(stripped)
        if decoded is not None:
            yield decoded
    if len(text) >= 8 and _BASE64_RE.fullmatch(text):
        decoded = _try_base64_decode(text)
        if decoded is not None:
            yield decoded
    if len(text) >= 2 and len(text) % 2 == 0 and _HEX_RE.fullmatch(text):
        try:
            yield bytes.fromhex(text).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass


def _matches_deny_pattern(text: str) -> bool:
    return any(pattern.search(text) for pattern, _reason in _DENY_PATTERNS)


def validate_slack_text(
    text: object,
    *,
    actor_id: str,
    channel_id: str,
    event_id: str,
) -> ExternalSlackInput:
    if not isinstance(text, str):
        raise SlackInputRejected("non-string-input")
    normalized = unicodedata.normalize("NFKC", text)
    if len(normalized) > MAX_SLACK_TEXT_LENGTH:
        raise SlackInputRejected("input-too-long")
    candidates = (normalized, *_one_level_decoded(normalized))
    for candidate in candidates:
        if _contains_disallowed_control(candidate):
            raise SlackInputRejected("disallowed-control-character")
        if _matches_deny_pattern(candidate):
            raise SlackInputRejected("injection-pattern")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return ExternalSlackInput(
        text=normalized,
        actor_id=actor_id,
        channel_id=channel_id,
        event_id=event_id,
        validation_version=VALIDATION_VERSION,
        digest=digest,
    )
