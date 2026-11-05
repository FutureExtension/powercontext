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

"""Concurrent embedding request coalescing and bounded vector caching.

PowerContext already batches the texts of one embedding call and reuses the vector of
an unchanged entry. It does not deduplicate work *across* calls: several scopes that
write the same corpus at the same time each pay for the same vectors, and a caller
that arrives while a request is still running pays for them a second time.

This module adds that missing cross-call layer. One wrapper instance is shared by every
caller inside one event loop. It merges the texts of concurrent calls into a small
number of bounded provider requests, lets a late caller join a request that is still
running, and remembers successful vectors in a bounded LRU cache.

The wrapper is deliberately thin: it speaks only the embedding port, so it can wrap any
deployment-fixed embedding model and be handed straight to
open_builtin_contexts(..., embedding_model=model).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import TYPE_CHECKING

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from powercontext.builtin.artifacts.memory.models import EmbeddingProfile
    from powercontext.builtin.inference.protocols import EmbeddingModel

__all__ = ["CoalescingEmbeddingModel"]


class _TextSlot:
    """One text waiting for, or holding, the vector of its provider request."""

    __slots__ = ("text", "future", "batch", "vector", "error")

    def __init__(self, text: str, future: asyncio.Future[None]) -> None:
        self.text = text
        self.future = future
        self.batch: _Batch | None = None
        self.vector: EmbeddingVector | None = None
        self.error: BaseException | None = None


class _Batch:
    """One underlying provider request and the texts it owns."""

    __slots__ = ("slots", "usage")

    def __init__(self, slots: tuple[_TextSlot, ...]) -> None:
        self.slots = slots
        self.usage = InferenceUsage(requests=0)


class CoalescingEmbeddingModel:
    """Coalesce concurrent embedding requests and cache successful vectors.

    The contract this wrapper honours:

    * Text sharing. One call, several calls inside the coalescing window, and calls
      that arrive while a request is still running share the same text. A late caller
      joins the running request instead of issuing a request of its own.
    * Batching and empty input. Every provider request carries at most
      max_batch_size distinct texts. An empty input never reaches the provider.
    * Caching. Only successful vectors are cached, the cache is bounded, and reading
      an entry refreshes its recency. cache_size=0 turns the cross-call cache off
      while still sharing requests that are still running.
    * Ordering. A call always receives one vector per input text, in its own input
      order, with duplicate positions preserved.
    * Partial failure. A provider error reaches every waiter that depends on that
      batch. A failed vector is never cached, so the text can be retried, and batches
      that do not depend on the failed one still complete.
    * Vector count. A provider that answers with a different number of vectors than
      texts fails the batch with ValueError.
    * Cancellation isolation. Cancelling one call never cancels provider work that
      other calls wait for, and never costs them their result.
    * Usage. One call reports the usage of the distinct provider batches it waited on,
      each batch counted once. A shared batch counts for every waiter. A call served
      entirely from the cache reports no requests.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        """Wrap one embedding model with coalescing and caching."""

        if max_batch_size < 1:
            raise ValueError("max_batch_size must be at least 1")  # noqa: TRY003
        if coalesce_ms < 0:
            raise ValueError("coalesce_ms must not be negative")  # noqa: TRY003
        if cache_size < 0:
            raise ValueError("cache_size must not be negative")  # noqa: TRY003
        self._model = model
        self.profile: EmbeddingProfile = model.profile
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._slots: dict[str, _TextSlot] = {}
        self._pending: list[str] = []
        self._dispatcher: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Embed one ordered batch of texts, sharing work with other callers."""

        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))
        self._bind_loop()
        vectors: dict[str, EmbeddingVector] = {}
        waited: list[_TextSlot] = []
        for text in dict.fromkeys(texts):
            cached = self._cache_get(text)
            if cached is not None:
                vectors[text] = cached
                continue
            slot = self._slots.get(text)
            if slot is None:
                slot = self._register(text)
            waited.append(slot)
        for slot in waited:
            # Shielding keeps a cancelled caller from cancelling the shared request.
            await asyncio.shield(slot.future)
        for slot in waited:
            if slot.error is not None:
                raise slot.error
        for slot in waited:
            if slot.vector is None:
                raise RuntimeError("embedding slot completed without a vector")  # noqa: TRY003
            vectors[slot.text] = slot.vector
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=self._usage_for(waited),
        )

    def _register(self, text: str) -> _TextSlot:
        """Claim one text for a provider request that has not run yet."""

        future = asyncio.get_running_loop().create_future()
        slot = _TextSlot(text, future)
        self._slots[text] = slot
        self._pending.append(text)
        self._ensure_dispatcher()
        return slot

    def _bind_loop(self) -> None:
        """Bind the wrapper to the running loop and drop work a closed loop abandoned."""

        loop = asyncio.get_running_loop()
        previous = self._loop
        if previous is loop:
            return
        self._loop = loop
        if previous is not None and previous.is_closed():
            # A closed loop can never settle those texts, so they must not be awaited again.
            self._slots.clear()
            self._pending.clear()
            self._dispatcher = None

    def _ensure_dispatcher(self) -> None:
        """Start the dispatcher when no live dispatcher is collecting pending texts."""

        dispatcher = self._dispatcher
        if (
            dispatcher is None
            or dispatcher.done()
            or dispatcher.get_loop() is not asyncio.get_running_loop()
        ):
            self._dispatcher = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        """Collect pending texts for one window, then hand them to the provider."""

        try:
            while True:
                if self._pending:
                    await asyncio.sleep(self._coalesce_seconds)
                texts = self._pending
                if not texts:
                    self._dispatcher = None
                    return
                self._pending = []
                self._dispatch(texts)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A broken dispatcher must not leave callers waiting forever.
            self._fail_pending(error)
            self._dispatcher = None

    def _dispatch(self, texts: Sequence[str]) -> None:
        """Split the collected texts into bounded provider requests."""

        for start in range(0, len(texts), self._max_batch_size):
            chunk = texts[start : start + self._max_batch_size]
            slots = tuple(
                slot for slot in (self._slots.get(text) for text in chunk) if slot is not None
            )
            if not slots:
                continue
            batch = _Batch(slots)
            for slot in slots:
                slot.batch = batch
            asyncio.create_task(self._run_batch(batch))

    async def _run_batch(self, batch: _Batch) -> None:
        """Run one provider request and settle every text that depends on it."""

        try:
            await self._settle_batch(batch)
        finally:
            self._fail_unsettled(batch)

    async def _settle_batch(self, batch: _Batch) -> None:
        """Ask the provider for one batch and settle its texts."""

        texts = tuple(slot.text for slot in batch.slots)
        try:
            vectors, usage = await self._embed_batch(texts)
        except asyncio.CancelledError as error:
            self._fail_batch(batch, error)
            raise
        except Exception as error:
            self._fail_batch(batch, error)
            return
        for slot, vector in zip(batch.slots, vectors, strict=True):
            slot.vector = vector
            self._slots.pop(slot.text, None)
            self._cache_put(slot.text, vector)
        batch.usage = usage
        for slot in batch.slots:
            if not slot.future.done():
                slot.future.set_result(None)

    async def _embed_batch(self, texts: tuple[str, ...]) -> tuple[tuple[EmbeddingVector, ...], InferenceUsage]:
        """Ask the provider for one batch and check that it answered completely."""

        result = await self._model.embed(texts)
        vectors = tuple(result.vectors)
        if len(vectors) != len(texts):
            raise ValueError(  # noqa: TRY003
                f"embedding provider returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors, result.usage

    def _fail_batch(self, batch: _Batch, error: BaseException) -> None:
        """Settle one failed batch without caching any of its vectors."""

        for slot in batch.slots:
            if slot.future.done():
                continue
            slot.error = error
            self._slots.pop(slot.text, None)
            slot.future.set_result(None)

    def _fail_unsettled(self, batch: _Batch) -> None:
        """Settle any text the batch did not settle, so that no waiter can hang."""

        unsettled = tuple(slot for slot in batch.slots if not slot.future.done())
        if not unsettled:
            return
        self._fail_batch(
            _Batch(unsettled),
            RuntimeError("embedding request did not settle"),  # noqa: TRY003
        )

    def _fail_pending(self, error: BaseException) -> None:
        """Settle every text that never reached the provider."""

        for text in self._pending:
            slot = self._slots.get(text)
            if slot is not None:
                self._fail_batch(_Batch((slot,)), error)
        self._pending = []

    def _cache_get(self, text: str) -> EmbeddingVector | None:
        """Return a cached vector and refresh its recency."""

        if self._cache_size <= 0:
            return None
        vector = self._cache.get(text)
        if vector is None:
            return None
        self._cache.move_to_end(text)
        return vector

    def _cache_put(self, text: str, vector: EmbeddingVector) -> None:
        """Remember one successful vector, evicting the least recently used entry."""

        if self._cache_size <= 0:
            return
        cache = self._cache
        cache[text] = vector
        cache.move_to_end(text)
        while len(cache) > self._cache_size:
            cache.popitem(last=False)

    def _usage_for(self, waited: Sequence[_TextSlot]) -> InferenceUsage:
        """Aggregate the usage of the distinct provider batches one call waited on."""

        batches: dict[_Batch, None] = {}
        for slot in waited:
            if slot.batch is not None:
                batches[slot.batch] = None
        requests = 0
        input_tokens: int | None = None
        output_tokens: int | None = None
        for batch in batches:
            usage = batch.usage
            requests += usage.requests
            if usage.input_tokens is not None:
                input_tokens = (input_tokens or 0) + usage.input_tokens
            if usage.output_tokens is not None:
                output_tokens = (output_tokens or 0) + usage.output_tokens
        return InferenceUsage(
            requests=max(requests, len(batches)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
