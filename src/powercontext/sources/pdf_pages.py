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

"""Page-level PDF capture with stable identity per physical page."""

from __future__ import annotations

import hashlib
import io
import math
from collections import Counter
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
_PAIR_CANDIDATES = 100
_RRF_K = 60.0
# A rare term that occurs in the document is a precise signal: the top few
# pages of its single term query are promoted on top of the pair fusion.
_SINGLE_TERM_MIN_IDF = 1.0
_SINGLE_TERM_WEIGHT = 2.0
_SINGLE_TERM_CANDIDATES = 3

# A captured page becomes one memory entry whose text is the document identity
# followed by the page text, and a memory entry holds at most 8192 UTF-8 bytes.
# A page that does not fit would make the whole ingest of the document fail, so
# its tail is trimmed instead.
MEMORY_ENTRY_TEXT_LIMIT = 8192


class PDFDocumentInput(BaseModel):
    """One complete PDF document addressed by a caller-stable identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a captured PDF document."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """Captured PDF page that can be used as Artifact evidence."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Return the stable identity of one captured PDF page."""

    _validate_document_id(document_id)
    if not isinstance(document_sha256, str) or len(document_sha256) != 64:
        raise ValueError("document_sha256 must be a 64 character hexadecimal digest")
    if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be a positive integer")
    identity = f"pdf:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) <= MAX_SOURCE_ID_LENGTH:
        return identity
    digest = hashlib.sha256(
        f"{document_id}\x00{document_sha256}\x00{page_number}".encode("utf-8")
    ).hexdigest()
    return f"pdf:{digest}"


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one complete PDF document."""

    document_id = value.document_id
    _validate_document_id(document_id)
    content = value.content
    if not isinstance(content, (bytes, bytearray)):
        raise ValueError("PDF content must be bytes")
    data = bytes(content)
    if not data:
        raise ValueError("PDF content must not be empty")
    document_sha256 = hashlib.sha256(data).hexdigest()
    texts = _extract_pages(data)
    return tuple(
        PDFPageInput(
            document_id=document_id,
            document_sha256=document_sha256,
            page_number=number,
            text=fit_page_text(document_id, text),
        )
        for number, text in enumerate(texts, start=1)
    )


def fit_page_text(document_id: str, text: str) -> str:
    """Return the page text that fits into one memory entry.

    The projection of a page carries the document identity and the page text,
    and the entry that the runtime stores holds that projection.  A page whose
    text exceeds the entry limit would make the ingest of the whole document
    fail, so the tail of that page is trimmed.  Financial reports repeat a
    running footer on every page, so the tail carries little evidence and the
    trim stays as small as the budget allows.  A page that fits is returned
    unchanged.
    """

    budget = MEMORY_ENTRY_TEXT_LIMIT - len(document_id.encode("utf-8")) - 1
    encoded = text.encode("utf-8")
    if len(encoded) <= budget:
        return text
    candidate = text.rstrip()
    if len(candidate.encode("utf-8")) <= budget:
        return candidate
    trimmed = encoded[:budget].decode("utf-8", errors="ignore")
    newline = trimmed.rfind("\n")
    if newline >= 0 and len(trimmed) - newline <= 200:
        return trimmed[: newline + 1]
    space = trimmed.rfind(" ")
    if space > 0:
        return trimmed[:space]
    return trimmed


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")


def _extract_pages(data: bytes) -> list[str]:
    """Return the extractable text of every physical page, in order."""

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as error:
        raise ValueError(f"PDF content cannot be parsed: {error}") from error
    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception as error:
            raise ValueError(f"PDF content cannot be decrypted: {error}") from error
        if not decrypted:
            raise ValueError("PDF content requires a password")
    try:
        pages = list(reader.pages)
    except Exception as error:
        raise ValueError(f"PDF content cannot be parsed: {error}") from error
    texts: list[str] = []
    for page in pages:
        try:
            extracted = page.extract_text()
        except Exception as error:
            raise ValueError(f"PDF page cannot be parsed: {error}") from error
        texts.append("" if extracted is None else extracted)
    return texts


class PDFPageAdapter:
    """Resolve and read the runtime's page-level PDF Source."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            definition_version=PDF_PAGE_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            source_id=source_id,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one captured PDF page without coupling consumers to the page Source."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple:
    """Return the distinct PDF pages that best answer one question.

    A long natural-language question rarely matches a page verbatim, and a long query also
    makes the lexical admission floor reject every page that does not echo most of the
    question. The question is therefore split into its lexical terms and looked up as
    adjacent term pairs: a short query is admitted far more easily and keeps the ranking
    close to the question's wording. The per-pair result lists are then fused with an
    inverse-document-frequency weighted reciprocal rank fusion, so a page that answers one
    rare pair outranks a page that echoes common words. Every returned citation is read back
    through the public Memory API, so it points at one exact stored page.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.artifacts.search import analyze_fts_query, analyze_text
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    terms = tuple(analyze_fts_query(question).split())
    if not terms:
        return ()
    weights, present = await _term_weights(memory, terms, analyze_text)
    queries = _pair_queries(terms, weights)
    if not queries:
        return ()
    single = tuple(
        term
        for term in dict.fromkeys(terms)
        if term in present and weights.get(term, 0.0) >= _SINGLE_TERM_MIN_IDF
    )

    scores: dict[str, float] = {}
    citations: dict[str, object] = {}
    for query, weight in queries:
        page = await memory.search(
            SearchMemoryRequest(query=query, mode="fts", limit=_PAIR_CANDIDATES)
        )
        for rank, hit in enumerate(page.hits, start=1):
            key = hit.entry_id
            citations.setdefault(
                key,
                MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                ),
            )
            scores[key] = scores.get(key, 0.0) + weight / (_RRF_K + rank)
    for term in single:
        weight = _SINGLE_TERM_WEIGHT * weights.get(term, 1.0)
        page = await memory.search(
            SearchMemoryRequest(query=term, mode="fts", limit=_PAIR_CANDIDATES)
        )
        for rank, hit in enumerate(page.hits[:_SINGLE_TERM_CANDIDATES], start=1):
            key = hit.entry_id
            citations.setdefault(
                key,
                MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                ),
            )
            scores[key] = scores.get(key, 0.0) + weight / (_RRF_K + rank)
    if not scores:
        return ()

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    selected: list[object] = []
    seen: set[tuple[str, ...]] = set()
    for entry_id, _score in ordered:
        if len(selected) >= limit:
            break
        citation = citations[entry_id]
        try:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
        except Exception:  # noqa: BLE001 - a vanished head must not break the search
            continue
        identity = tuple(sorted(reference.source_id for reference in record.entry.sources))
        if not identity or identity in seen:
            continue
        seen.add(identity)
        selected.append(citation)
    return tuple(selected)


def _pair_queries(terms: tuple[str, ...], weights: dict[str, float]) -> tuple[tuple[str, float], ...]:
    """Return the adjacent term-pair queries and the weight of each pair."""

    if len(terms) < 2:
        return tuple((term, weights.get(term, 1.0)) for term in terms)
    queries: list[tuple[str, float]] = []
    for index in range(len(terms) - 1):
        left, right = terms[index], terms[index + 1]
        weight = weights.get(left, 1.0)
        queries.append((f"{left} {right}", weight))
    return tuple(queries)

async def _term_weights(
    memory, terms: tuple[str, ...], analyze_text
) -> tuple[dict[str, float], set[str]]:
    """Return the inverse document frequency of every question term.

    The second value holds the terms that occur in at least one page, so that
    a single term query is only issued for a term that can actually match.
    """

    total = 0
    frequencies: Counter[str] = Counter()
    try:
        listing = await memory.list(include_inactive=True)
    except Exception:  # noqa: BLE001 - the listing is an optimisation, not a requirement
        return {term: 1.0 for term in terms}, set()
    for record in listing.entries:
        total += 1
        for term in set(analyze_text(record.entry.text).split()):
            frequencies[term] += 1
    if not total:
        return {term: 1.0 for term in terms}, set()
    weights: dict[str, float] = {}
    for term in terms:
        document_frequency = frequencies.get(term, 0)
        weights[term] = math.log(1 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
    present = {term for term in terms if frequencies.get(term, 0) > 0}
    return weights, present


PDF_PAGE_ADAPTER = PDFPageAdapter()
PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDF_PAGE_ADAPTER,
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(PDFPageTextEvidenceProjection(),),
)


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
