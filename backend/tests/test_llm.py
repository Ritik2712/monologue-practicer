"""The Ollama client, against a scripted stand-in for the Ollama server."""

import json

import httpx
import pytest

from app import llm
from app.llm import LlmError, Message, OllamaChat
from app.pipeline.errors import JobCancelled

INSTALLED = {"models": [{"name": "llama3.1:8b", "model": "llama3.1:8b"}]}
MESSAGES = [Message("system", "Be brief."), Message("user", "Coach me.")]
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def stream(*pieces: dict) -> httpx.Response:
    return httpx.Response(200, content="\n".join(json.dumps(piece) for piece in pieces) + "\n")


def piece(text: str) -> dict:
    return {"message": {"role": "assistant", "content": text}, "done": False}


def done(**fields) -> dict:
    return {"message": {"content": ""}, "done": True, "done_reason": "stop", **fields}


class FakeOllama:
    """Answers /api/tags and /api/chat, and keeps every request it received."""

    def __init__(self, chat: httpx.Response | Exception | None = None, tags=INSTALLED) -> None:
        self.chat = chat
        self.tags = tags
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/tags":
            if isinstance(self.tags, Exception):
                raise self.tags
            return httpx.Response(200, json=self.tags)
        if isinstance(self.chat, Exception):
            raise self.chat
        return self.chat

    @property
    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def client(server: FakeOllama, **kwargs) -> OllamaChat:
    return OllamaChat("llama3.1:8b", transport=httpx.MockTransport(server), **kwargs)


def test_the_model_is_ready_when_ollama_runs_and_has_it_installed():
    assert client(FakeOllama()).status() == "ready"
    # A name without a tag means the "latest" one.
    server = FakeOllama(tags={"models": [{"name": "mistral:latest"}]})
    assert OllamaChat("mistral", transport=httpx.MockTransport(server)).status() == "ready"


def test_a_missing_model_is_reported_and_never_downloaded():
    server = FakeOllama(tags={"models": [{"name": "mistral:latest"}]})
    chat = client(server)
    assert chat.status() == "model_missing"
    with pytest.raises(LlmError) as raised:
        chat.complete_json(MESSAGES, SCHEMA, max_tokens=100)
    assert raised.value.code == "model_missing"
    assert raised.value.message == "The AI model 'llama3.1:8b' is not installed in Ollama."
    # Only ever asked what is installed: nothing was pulled and nothing was generated.
    assert set(server.paths) == {"/api/tags"}


def test_ollama_not_running_is_reported_plainly():
    server = FakeOllama(tags=httpx.ConnectError("refused"))
    chat = client(server)
    assert chat.status() == "not_running"
    with pytest.raises(LlmError) as raised:
        chat.complete_json(MESSAGES, SCHEMA, max_tokens=100)
    assert raised.value.code == "not_running"


@pytest.mark.parametrize(
    "url", ["http://192.168.1.20:11434", "https://api.example.com", "http://ollama.internal:11434"]
)
def test_an_address_on_another_machine_is_refused_without_sending_anything(url):
    server = FakeOllama(stream(done()))
    chat = client(server, base_url=url)
    assert chat.status() == "not_local"
    with pytest.raises(LlmError) as raised:
        chat.complete_json(MESSAGES, SCHEMA, max_tokens=100)
    assert raised.value.code == "not_local"
    assert server.requests == []


@pytest.mark.parametrize(
    "url", ["http://localhost:11434", "http://127.0.0.1:11434/", "http://[::1]:11434"]
)
def test_addresses_on_this_computer_are_accepted(url):
    assert llm.is_local_url(url)


def test_proxy_settings_in_the_environment_are_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:8080")
    with client(FakeOllama())._client(1.0) as http:
        assert http.trust_env is False


def test_the_answer_arrives_in_pieces_and_is_put_together():
    server = FakeOllama(
        stream(piece('{"ok"'), piece(": true}"), done(prompt_eval_count=700, eval_count=12))
    )
    reply = client(server).complete_json(MESSAGES, SCHEMA, max_tokens=600)

    assert reply.text == '{"ok": true}'
    assert (reply.truncated, reply.prompt_tokens, reply.output_tokens) == (False, 700, 12)
    assert server.paths == ["/api/tags", "/api/chat"]
    sent = json.loads(server.requests[1].content)
    assert sent == {
        "model": "llama3.1:8b",
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Coach me."},
        ],
        "stream": True,
        "format": SCHEMA,
        "options": {"temperature": 0.3, "num_ctx": 8192, "num_predict": 600},
    }


def test_an_answer_that_ran_out_of_room_is_marked_as_cut_off():
    out_of_tokens = FakeOllama(stream(piece('{"ok"'), done(done_reason="length")))
    assert client(out_of_tokens).complete_json(MESSAGES, SCHEMA, max_tokens=5).truncated

    context_full = FakeOllama(stream(piece("{}"), done(prompt_eval_count=4000, eval_count=96)))
    reply = client(context_full, context_tokens=4096).complete_json(
        MESSAGES, SCHEMA, max_tokens=100
    )
    assert reply.truncated


@pytest.mark.parametrize(
    ("chat", "code"),
    [
        (httpx.Response(500, content="boom"), "model_error"),
        (stream({"error": "out of memory"}), "model_error"),
        (stream(piece("{")), "model_error"),  # the stream ended without a final piece
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ReadError("gone"), "not_running"),
    ],
)
def test_failures_while_answering_become_errors_with_a_safe_message(chat, code):
    with pytest.raises(LlmError) as raised:
        client(FakeOllama(chat)).complete_json(MESSAGES, SCHEMA, max_tokens=100)
    assert raised.value.code == code
    assert "boom" not in raised.value.message and "memory" not in raised.value.message


def test_a_cancelled_job_stops_the_answer_part_way(monkeypatch):
    monkeypatch.setattr(llm, "CHECK_INTERVAL_SECONDS", 0)
    server = FakeOllama(stream(piece("a"), piece("b"), piece("c"), done()))
    checks = 0

    def check() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise JobCancelled

    with pytest.raises(JobCancelled):
        client(server).complete_json(MESSAGES, SCHEMA, max_tokens=100, check=check)
    assert checks == 2


def test_an_answer_that_takes_too_long_is_abandoned(monkeypatch):
    moments = iter(range(0, 10_000, 100))
    monkeypatch.setattr(llm.time, "monotonic", lambda: next(moments))
    server = FakeOllama(stream(piece("a"), piece("b"), piece("c"), done()))
    with pytest.raises(LlmError) as raised:
        client(server, timeout_seconds=150).complete_json(MESSAGES, SCHEMA, max_tokens=100)
    assert raised.value.code == "timeout"
    assert raised.value.message == (
        "The AI model did not finish within 150 seconds, so it was stopped."
    )
