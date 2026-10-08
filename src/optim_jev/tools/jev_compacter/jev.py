from __future__ import annotations

import json
import math
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Mapping

from .config import DEFAULT_MODEL, SYSTEM_ONE_URL
from .types import JevCompactionError, JevQuestions

# Jev's price in USD per million tokens.
INPUT_USD_PER_MTOK = 0.04
OUTPUT_USD_PER_MTOK = 0.0


def parse_response(status: int, ok: bool, text: str) -> dict[str, Any]:
    if not ok:
        raise JevCompactionError(f"Jev request failed ({status}): {text[:200]}")
    try:
        parsed = json.loads(text)
    except ValueError as err:
        raise JevCompactionError("Jev returned malformed JSON") from err
    if not isinstance(parsed, dict) or not isinstance(parsed.get("answers"), dict):
        raise JevCompactionError("Jev response is missing answers")
    return parsed


def noul_answer(answers: Mapping[str, Any], name: str) -> float:
    answer = answers.get(name)
    value = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise JevCompactionError(f"Invalid Jev answer for {name}")
    return float(value)


class JevClient:
    """Asks Jev over HTTP; the key defaults to TYPESAFE_API_KEY."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = SYSTEM_ONE_URL,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._lock = threading.Lock()  # the compacter asks from several threads
        self._requests = 0
        self._failed = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def usage(self) -> dict[str, Any]:
        """Raw totals over every `ask` so far, as the API reported them, and their price."""
        with self._lock:
            return {
                "model": self._model,
                "requests": self._requests,
                "failed": self._failed,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "input_usd_per_mtok": INPUT_USD_PER_MTOK,
                "output_usd_per_mtok": OUTPUT_USD_PER_MTOK,
                "cost_usd": round(
                    (self._input_tokens * INPUT_USD_PER_MTOK + self._output_tokens * OUTPUT_USD_PER_MTOK) / 1e6, 8
                ),
            }

    def _count(self, parsed: dict[str, Any] | None) -> None:
        usage = parsed.get("usage") if parsed else None
        usage = usage if isinstance(usage, dict) else {}

        def count(key: str) -> int:
            value = usage.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else 0

        with self._lock:
            self._requests += 1
            self._failed += parsed is None
            self._input_tokens += count("input_tokens")
            self._output_tokens += count("output_tokens")

    def ask(self, state: Mapping[str, Any], questions: JevQuestions) -> dict[str, Any]:
        if not self._api_key:
            raise JevCompactionError("TYPESAFE_API_KEY is not configured")
        try:
            parsed = self._post(state, questions)
        except JevCompactionError:
            self._count(None)
            raise
        self._count(parsed)
        return parsed

    def _post(self, state: Mapping[str, Any], questions: JevQuestions) -> dict[str, Any]:
        body = json.dumps({"model": self._model, "state": state, "questions": questions})
        request = urllib.request.Request(
            self._base_url,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return parse_response(response.status, True, response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return parse_response(err.code, False, err.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError) as err:
            raise JevCompactionError(f"Jev request failed: {err}") from err
