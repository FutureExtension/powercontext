"""The page text has to fit into one memory entry without losing its terms."""

from __future__ import annotations

import re

from powercontext.sources.pdf_pages import (
    MEMORY_ENTRY_TEXT_LIMIT,
    MIN_TERM_RETENTION,
    fit_page_text,
)

DOC = "PEPSICO_2022_10K"
BUDGET = MEMORY_ENTRY_TEXT_LIMIT - len(DOC) - 1
TERM = re.compile(r"[A-Za-z]+|\d+")

LINE = (
    "consolidated net revenue increased in 2022 compared with 2021 driven by organic volume growth "
    "and effective net pricing across the segments reported in the consolidated statements"
)


def _page(lines: int) -> str:
    return "\n".join(f"note {number} {LINE}" for number in range(lines))


def _terms(text: str) -> list[str]:
    return TERM.findall(text)


def test_page_that_fits_is_returned_unchanged() -> None:
    text = "Revenue 2022\n" * 10
    assert fit_page_text(DOC, text) == text


def test_page_about_ten_percent_over_the_limit_keeps_most_terms() -> None:
    # A realistic financial page: 13 adjacent tokens per 155 bytes, which is
    # close to the density of the real pages that exceed the entry limit.
    lines = (BUDGET // len(_page(1)) * 100) // 100 + 1
    text = _page(lines)
    while len(text.encode("utf-8")) <= BUDGET:
        lines += 1
        text = _page(lines)
    overhead = len(text.encode("utf-8")) / BUDGET
    assert 1.0 < overhead < 1.2
    fitted = fit_page_text(DOC, text)
    assert len(fitted.encode("utf-8")) <= BUDGET
    assert len((DOC + "\n" + fitted).encode("utf-8")) <= MEMORY_ENTRY_TEXT_LIMIT
    # The acceptance compares pages by term count, so the shortened page has to
    # keep at least the accepted share of the terms.
    kept = len(_terms(fitted)) / len(_terms(text))
    assert kept >= MIN_TERM_RETENTION, kept


def test_whitespace_is_collapsed_without_losing_a_term() -> None:
    # The raw page is over the entry limit, but the padding is not terms, so
    # collapsing it makes the page fit with every term intact.
    text = "Revenue    2022\t\tincreased\n\n   with organic volume growth     \n" * 160
    assert len(text.encode("utf-8")) > BUDGET
    fitted = fit_page_text(DOC, text)
    assert len((DOC + "\n" + fitted).encode("utf-8")) <= MEMORY_ENTRY_TEXT_LIMIT
    assert _terms(fitted) == _terms(text)


def test_a_sparse_region_is_dropped_instead_of_the_dense_terms() -> None:
    # A page whose tail is dense and whose middle is a long, low density
    # region: shedding the sparse region frees the bytes and costs far fewer
    # terms than cutting the dense text.
    sparse = "\n".join(f"sparsemarker{'x' * 140} {number}" for number in range(50))
    dense = "\n".join(f"tail{number} revenue" for number in range(500))
    text = f"{dense}\n{sparse}"
    assert len(text.encode("utf-8")) > BUDGET
    fitted = fit_page_text(DOC, text)
    assert len((DOC + "\n" + fitted).encode("utf-8")) <= MEMORY_ENTRY_TEXT_LIMIT
    kept = len(_terms(fitted)) / len(_terms(text))
    assert kept >= MIN_TERM_RETENTION, kept
    # The dense terms all survive; only the sparse region gives up the bytes.
    assert fitted.count("tail") == text.count("tail")
    assert fitted.count("sparsemarker") < text.count("sparsemarker")


def test_far_over_long_page_is_trimmed_to_the_limit() -> None:
    text = _page(4000)
    fitted = fit_page_text(DOC, text)
    assert len(fitted.encode("utf-8")) <= BUDGET
    assert len((DOC + "\n" + fitted).encode("utf-8")) <= MEMORY_ENTRY_TEXT_LIMIT
    assert fitted.startswith("note 0 ")


def test_document_identity_that_does_not_fit_is_left_alone() -> None:
    # The identity alone is larger than one entry, so no page of this
    # document can be stored.  The page is returned unchanged instead of being
    # cut from the wrong end.
    text = "line revenue 2022\n" * 100
    assert fit_page_text("D" * 9000, text) == text


def test_trim_does_not_split_a_multibyte_character() -> None:
    text = "收入 " * 4000
    fitted = fit_page_text("doc", text)
    assert len(("doc" + "\n" + fitted).encode("utf-8")) <= MEMORY_ENTRY_TEXT_LIMIT
    fitted.encode("utf-8").decode("utf-8")
