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
import re
from collections import Counter
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
_TOKEN = re.compile(r"[a-z0-9]+")
_CANDIDATE_FACTOR = 8
_MIN_CANDIDATES = 64


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
            text=text,
        )
        for number, text in enumerate(texts, start=1)
    )


def _validate_document_id(document_id: str) -> None:
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")


def _extract_pages(data: bytes) -> list[str]:
    """Return the extractable text of every physical page, in order."""

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

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

    The pages are read back through the public Memory API, so every returned citation is
    an exact reference to one stored page.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    terms = _question_terms(question)
    page = await memory.search(
        SearchMemoryRequest(query=question, mode="fts", limit=max(limit * _CANDIDATE_FACTOR, _MIN_CANDIDATES))
    )
    ranked: list[tuple[float, int, MemoryCitation, str]] = []
    seen: set[str] = set()
    for rank, hit in enumerate(page.hits):
        citation = MemoryCitation(
            memory_ref=hit.memory_ref,
            entry_id=hit.entry_id,
            entry_version_id=hit.entry_version_id,
        )
        try:
            entry = await memory.get(GetMemoryEntryRequest(citation=citation))
        except Exception:  # noqa: BLE001 - a vanished head must not break the search
            continue
        identity = _entry_identity(entry)
        if identity in seen:
            continue
        seen.add(identity)
        ranked.append((_overlap_score(terms, entry.entry.text), -rank, citation, identity))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = ranked[:limit]
    return tuple(citation for _, _, citation, _ in selected)


def _entry_identity(entry) -> str:
    return "|".join(sorted(reference.source_id for reference in entry.entry.sources))


def _question_terms(question: str) -> Counter:
    return Counter(_TOKEN.findall(question.lower()))


def _overlap_score(terms: Counter, text: str) -> float:
    if not terms:
        return 0.0
    tokens = _TOKEN.findall(text.lower())
    counts = Counter(tokens)
    score = 0.0
    for term, weight in terms.items():
        found = counts.get(term, 0)
        if found:
            score += weight * (1.0 + found ** 0.5)
    return score


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
