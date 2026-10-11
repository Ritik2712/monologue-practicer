"""Talking to the local language model.

This file is the only place that knows a language model is reached through Ollama. The rest
of the app sees the small `ChatModel` interface below, so a different way of calling a model
could be added later by writing one more class, without touching the coaching code.

Three promises this file keeps:

- It only ever talks to Ollama on this computer. An address pointing anywhere else is refused.
- It never downloads a model. If the configured model is not installed, it says so.
- It sends text only: the prompt it is given. It has no access to audio.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx

ModelStatus = Literal["ready", "not_running", "model_missing", "not_local"]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# How long to wait for Ollama to answer a quick question such as "which models are installed?".
QUICK_TIMEOUT_SECONDS = 3.0
# Cancellation is checked between pieces of the answer, at most this often.
CHECK_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class Reply:
    text: str
    # True when the answer was cut off: it ran out of room, so it is not complete JSON.
    truncated: bool
    seconds: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class LlmError(Exception):
    """The model could not give an answer. `message` is safe to show to the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ChatModel(Protocol):
    name: str
    # How many tokens the prompt and the answer may take together.
    context_tokens: int

    def status(self) -> ModelStatus:
        """A quick check that the model could answer right now."""

    def complete_json(
        self,
        messages: list[Message],
        schema: dict,
        *,
        max_tokens: int,
        check: Callable[[], None] = lambda: None,
    ) -> Reply:
        """Asks for an answer that follows `schema`. `check` may raise to abandon the call."""


STATUS_MESSAGES: dict[str, str] = {
    "not_running": ("Ollama is not running on this computer, so the AI model could not be asked."),
    "model_missing": "The AI model is not installed in Ollama.",
    "not_local": (
        "OLLAMA_BASE_URL does not point at this computer. Nothing is sent to other machines."
    ),
}


def is_local_url(url: str) -> bool:
    try:
        return urlparse(url).hostname in LOCAL_HOSTS
    except ValueError:
        return False


class OllamaChat:
    """Calls the Ollama server running on this computer."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 180,
        context_tokens: int = 8192,
        temperature: float = 0.3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.context_tokens = context_tokens
        self.temperature = temperature
        self.transport = transport

    def _client(self, read_timeout: float) -> httpx.Client:
        # trust_env=False: proxy settings in the environment are ignored, so a request meant
        # for this computer can never be routed through another one.
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(QUICK_TIMEOUT_SECONDS, read=read_timeout),
            trust_env=False,
            transport=self.transport,
        )

    def status(self) -> ModelStatus:
        if not is_local_url(self.base_url):
            return "not_local"
        try:
            with self._client(QUICK_TIMEOUT_SECONDS) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                installed = response.json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return "not_running"
        names = {entry.get("name") for entry in installed} | {
            entry.get("model") for entry in installed
        }
        wanted = {self.name} if ":" in self.name else {self.name, f"{self.name}:latest"}
        return "ready" if names & wanted else "model_missing"

    def complete_json(
        self,
        messages: list[Message],
        schema: dict,
        *,
        max_tokens: int,
        check: Callable[[], None] = lambda: None,
    ) -> Reply:
        status = self.status()
        if status != "ready":
            message = STATUS_MESSAGES[status]
            if status == "model_missing":
                message = f"The AI model '{self.name}' is not installed in Ollama."
            raise LlmError(status, message)

        body = {
            "model": self.name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            # The answer arrives in pieces, so a cancelled job can stop it part-way.
            "stream": True,
            # Ollama only lets the model produce text that fits this JSON schema.
            "format": schema,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_tokens,
                "num_predict": max_tokens,
            },
        }
        started = time.monotonic()
        deadline = started + self.timeout_seconds
        last_check = started
        parts: list[str] = []
        final: dict = {}
        try:
            with (
                self._client(self.timeout_seconds) as client,
                client.stream("POST", "/api/chat", json=body) as response,
            ):
                if response.status_code != 200:
                    raise LlmError(
                        "model_error", f"Ollama refused the request ({response.status_code})."
                    )
                for line in response.iter_lines():
                    if not line:
                        continue
                    piece = json.loads(line)
                    if piece.get("error"):
                        raise LlmError("model_error", "Ollama reported an error while answering.")
                    parts.append(piece.get("message", {}).get("content", ""))
                    if piece.get("done"):
                        final = piece
                        break
                    now = time.monotonic()
                    if now > deadline:
                        raise LlmError("timeout", self._timeout_message())
                    if now - last_check >= CHECK_INTERVAL_SECONDS:
                        last_check = now
                        # Raising here leaves the `with` block, which closes the connection;
                        # Ollama stops generating when the caller hangs up.
                        check()
        except httpx.TimeoutException:
            raise LlmError("timeout", self._timeout_message()) from None
        except (httpx.HTTPError, ValueError):
            raise LlmError(
                "not_running", "The connection to Ollama was lost while it was answering."
            ) from None

        if not final:
            raise LlmError("model_error", "Ollama stopped before finishing its answer.")
        prompt_tokens = final.get("prompt_eval_count")
        output_tokens = final.get("eval_count")
        used = (prompt_tokens or 0) + (output_tokens or 0)
        return Reply(
            text="".join(parts),
            truncated=final.get("done_reason") == "length" or used >= self.context_tokens,
            seconds=time.monotonic() - started,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )

    def _timeout_message(self) -> str:
        return (
            f"The AI model did not finish within {self.timeout_seconds:g} seconds, so it was "
            "stopped."
        )
