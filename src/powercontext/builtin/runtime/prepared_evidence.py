# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pure helpers that cut candidate text into literal, query-scored evidence spans."""

from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_SENTENCE_TERMINATORS = ".!?;。！？；"
_CLOSING_MARKS = "\"'\u201d\u2019\uff09\u3011\u300b"


def split_segments(text: str) -> tuple[tuple[int, int], ...]:
    """Split one text into literal sentence spans, preserving character offsets.

    The spans cover the original text exactly once and in order. A terminator only ends a
    segment when the next character is whitespace or the end of the text, so decimals and
    abbreviations such as ``3.14`` or ``U.S.A.`` stay inside one segment.
    """

    spans: list[tuple[int, int]] = []
    length = len(text)
    start = 0
    index = 0
    while index < length:
        char = text[index]
        if char in _SENTENCE_TERMINATORS:
            end = index + 1
            while end < length and text[end] in _CLOSING_MARKS:
                end += 1
            if end >= length or text[end].isspace():
                spans.append((start, end))
                while end < length and text[end].isspace():
                    end += 1
                start = end
                index = end
                continue
        if char == "\n":
            spans.append((start, index))
            end = index
            while end < length and text[end].isspace():
                end += 1
            start = end
            index = end
            continue
        index += 1
    if start < length:
        spans.append((start, length))

    trimmed: list[tuple[int, int]] = []
    for span_start, span_end in spans:
        while span_start < span_end and text[span_start].isspace():
            span_start += 1
        while span_end > span_start and text[span_end - 1].isspace():
            span_end -= 1
        if span_end > span_start:
            trimmed.append((span_start, span_end))
    return tuple(trimmed)


def query_terms(query: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the comparable word tokens and CJK fragments of one query."""

    words = tuple(_WORD.findall(query.lower()))
    cjk: list[str] = []
    for run in _CJK.findall(query):
        if len(run) == 1:
            cjk.append(run)
            continue
        cjk.extend(run[index : index + 2] for index in range(len(run) - 1))
    return words, tuple(cjk)


def score_segment(words: tuple[str, ...], cjk: tuple[str, ...], segment: str) -> float:
    """Score one literal segment against the query terms it contains."""

    if not words and not cjk:
        return 0.0
    lowered = segment.lower()
    tokens = _WORD.findall(lowered)
    counts = Counter(tokens)
    distinct = 0
    occurrences = 0
    for word in set(words):
        found = counts.get(word, 0)
        if found:
            distinct += 1
            occurrences += min(found, 3)
    cjk_hits = sum(1 for fragment in set(cjk) if fragment in lowered)
    return distinct * 2.0 + occurrences + cjk_hits * 3.0


def character_overlap(query: str, segment: str) -> float:
    """Return a coarse fallback affinity for segments without any query word."""

    left = set(query.lower()) - set(" \t\r\n")
    if not left:
        return 0.0
    right = set(segment.lower())
    return len(left & right) / len(left)


def merge_spans(text: str, spans: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """Merge spans of one text that overlap or are separated only by whitespace."""

    if not spans:
        return ()
    ordered = sorted(spans)
    merged: list[tuple[int, int]] = [ordered[0]]
    for span_start, span_end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if span_start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, span_end))
            continue
        if text[previous_end:span_start].strip():
            merged.append((span_start, span_end))
            continue
        merged[-1] = (previous_start, span_end)
    return tuple(merged)


__all__ = [
    "character_overlap",
    "merge_spans",
    "query_terms",
    "score_segment",
    "split_segments",
]
