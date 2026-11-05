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

"""HTTP reranking service adapter for coarse Memory search candidates."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

HTTP_RERANKER_POLICY_ID = "http-cross-encoder-v1"

_RERANK_RESPONSE_FIELDS = frozenset({"scores"})
_RERANK_SCORE_FIELDS = frozenset({"rank", "score"})


class HTTPMemoryReranker:
    """Select coarse Memory hits with scores served by an external HTTP reranker.

    The service caps how many candidates one request may carry, so the pool is split
    into batches. Batching only shapes the transport: every request keeps the
    candidate's original one-based rank from the *complete* pool, and the final
    selection is taken from the scores of the whole pool in a single pass. The result
    therefore does not depend on how the pool happened to be split, and a candidate
    selected from a later batch keeps the identity of the candidate that was scored.

    The reranker only chooses which candidates survive and in which order. It never
    rewrites candidate text, Memory artifacts, entry ids, or entry version ids.

    The caller owns the ``httpx.AsyncClient``; this adapter never closes it.
    """

    policy_id: str

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = HTTP_RERANKER_POLICY_ID,
    ) -> None:
        """Bind one reranking endpoint, its client, and the per-request batch ceiling."""

        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("reranker endpoint must be a non-blank string")  # noqa: TRY003
        if not callable(getattr(client, "post", None)):
            raise ValueError("reranker client must expose a post method")  # noqa: TRY003
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("reranker batch size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id:
            raise ValueError("reranker policy id must be a non-empty string")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Return the global top ``limit`` ranks, as scored by the service.

        An invalid request or an invalid service response fails with ``ValueError``.
        Transport failures are left alone: a non-2xx response raises the ``httpx``
        status error and a network failure raises the ``httpx`` transport error, so a
        caller can tell a broken service apart from a rejected request.
        """

        pool = tuple(candidates)
        self._validate_request(query, pool, limit)
        scores: dict[int, float] = {}
        requests = 0
        for ranks in self._batches(len(pool)):
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [{"rank": rank, "text": pool[rank - 1].text} for rank in ranks],
                },
            )
            requests += 1
            response.raise_for_status()
            scores.update(self._read_scores(response, ranks))
        return MemoryRerankDecision(
            selected_ranks=self._select(scores, limit),
            usage=InferenceUsage(requests=requests),
        )

    def _validate_request(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
    ) -> None:
        """Reject a rerank request the service could not answer meaningfully."""

        if not isinstance(query, str) or not query:
            raise ValueError("rerank requires a non-empty query")  # noqa: TRY003
        if not candidates:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

    def _batches(self, candidate_count: int) -> tuple[tuple[int, ...], ...]:
        """Split the pool into batches of original ranks, never renumbering a candidate."""

        return tuple(
            tuple(range(start + 1, min(start + self._batch_size, candidate_count) + 1))
            for start in range(0, candidate_count, self._batch_size)
        )

    def _read_scores(self, response: httpx.Response, ranks: tuple[int, ...]) -> dict[int, float]:
        """Validate one batch response and map every original rank to its score."""

        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError("reranker response is not valid JSON") from error
        if not isinstance(payload, dict) or set(payload) != _RERANK_RESPONSE_FIELDS:
            raise ValueError("reranker response must contain exactly one scores field")  # noqa: TRY003
        records = payload["scores"]
        if not isinstance(records, list):
            raise ValueError("reranker scores must be a list")  # noqa: TRY003
        expected = set(ranks)
        scores: dict[int, float] = {}
        for record in records:
            rank, score = self._read_score(record)
            if rank not in expected:
                raise ValueError(f"reranker response scored a rank outside its batch: {rank}")  # noqa: TRY003
            if rank in scores:
                raise ValueError(f"reranker response scored a rank twice: {rank}")  # noqa: TRY003
            scores[rank] = score
        if set(scores) != expected:
            raise ValueError("reranker response must score every candidate of its batch exactly once")  # noqa: TRY003
        return scores

    def _read_score(self, record: Any) -> tuple[int, float]:
        """Read one score record, rejecting anything the protocol does not allow."""

        if not isinstance(record, dict) or set(record) != _RERANK_SCORE_FIELDS:
            raise ValueError("reranker score must contain exactly one rank and one score field")  # noqa: TRY003
        rank = record["rank"]
        score = record["score"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("reranker rank must be an integer")  # noqa: TRY003
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError("reranker score must be a number")  # noqa: TRY003
        value = float(score)
        if not math.isfinite(value):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        return rank, value

    def _select(self, scores: Mapping[int, float], limit: int) -> tuple[int, ...]:
        """Take the global top ranks: score descending, original rank ascending on ties."""

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return tuple(rank for rank, _ in ordered[:limit])


__all__ = [
    "HTTP_RERANKER_POLICY_ID",
    "HTTPMemoryReranker",
]
