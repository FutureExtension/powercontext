"""Minimal MiniMax chat client.

The client speaks the OpenAI compatible chat completion protocol that MiniMax
publishes, so it only needs the endpoint, the model name and an API key.  The
key is read from the environment and never stored in the repository.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax endpoint cannot be used."""


class MiniMaxClient:
    """Chat completion client for the MiniMax open platform."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Send one prompt and return the assistant answer."""

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps(
            {"model": self._model, "messages": messages, "temperature": 0.2}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise MiniMaxError(f"HTTP {error.code}: {detail[:400]}") from error
        except urllib.error.URLError as error:
            raise MiniMaxError(f"cannot reach MiniMax: {error.reason}") from error

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise MiniMaxError(f"unexpected response: {json.dumps(body)[:400]}") from error
