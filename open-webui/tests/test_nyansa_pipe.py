import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.nyansa_pipe import Pipe, last_user_message

ANSWER = {
    "answer": "L'apprêt dure 12 heures [1].\n\nSources :\n[1] Pain au levain (Recettes/Pain au levain.md)",
    "found": True,
    "cited": True,
    "sources": [
        {"n": 1, "path": "Recettes/Pain au levain.md", "title": "Pain au levain", "sections": ["Pain > Fermentation"]}
    ],
}


def body(question: str) -> dict[str, Any]:
    return {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": question}]}


@pytest.fixture
def requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def n8n(monkeypatch: pytest.MonkeyPatch, requests: list[httpx.Request]) -> Callable[[httpx.Response], None]:
    """Replaces n8n with a stub that records the requests and returns the given response."""

    def answer_with(response: httpx.Response) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return response

        real_client = httpx.AsyncClient

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)

    return answer_with


def configured() -> Pipe:
    pipe = Pipe()
    pipe.valves.WEBHOOK_TOKEN = "secret-token"
    return pipe


async def test_asks_n8n_and_returns_the_answer_with_its_citations(
    n8n: Callable[[httpx.Response], None], requests: list[httpx.Request]
) -> None:
    n8n(httpx.Response(200, json=ANSWER))
    events: list[dict[str, Any]] = []

    async def emitter(event: dict[str, Any]) -> None:
        events.append(event)

    text = await configured().pipe(body("Combien dure l'apprêt ?"), __event_emitter__=emitter)

    assert text == ANSWER["answer"]
    [request] = requests
    assert str(request.url) == "http://nyansa-n8n:5678/webhook/nyansa-chat"
    assert request.headers["x-nyansa-token"] == "secret-token"
    assert json.loads(request.content) == {"question": "Combien dure l'apprêt ?"}
    assert [event["type"] for event in events] == ["status", "status", "citation"]
    assert events[-1]["data"] == {
        "source": {"name": "[1] Pain au levain"},
        "document": ["Pain > Fermentation"],
        "metadata": [{"source": "Recettes/Pain au levain.md"}],
    }


async def test_works_without_an_event_emitter(n8n: Callable[[httpx.Response], None]) -> None:
    n8n(httpx.Response(200, json=ANSWER))
    assert await configured().pipe(body("question")) == ANSWER["answer"]


async def test_asks_for_the_token_before_calling_n8n(
    n8n: Callable[[httpx.Response], None], requests: list[httpx.Request]
) -> None:
    n8n(httpx.Response(200, json=ANSWER))
    assert "WEBHOOK_TOKEN" in await Pipe().pipe(body("question"))
    assert requests == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403, text="Authorization data is wrong!"), "n8n refuse le jeton"),
        (httpx.Response(500, json={"message": "Error in workflow"}), "n8n a répondu HTTP 500"),
        (httpx.Response(200, text="not json"), "Réponse inattendue de n8n"),
        (httpx.Response(200, json={"no": "answer"}), "Réponse inattendue de n8n"),
    ],
)
async def test_explains_n8n_failures(
    n8n: Callable[[httpx.Response], None], response: httpx.Response, message: str
) -> None:
    n8n(response)
    assert (await configured().pipe(body("question"))).startswith(message)


async def test_explains_an_unreachable_n8n(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(refuse), **kwargs)
    )
    assert await configured().pipe(body("question")) == "Nyansa est injoignable : ConnectError connection refused"


def test_last_user_message_reads_text_parts_and_ignores_other_roles() -> None:
    multimodal = {
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": [{"type": "text", "text": " second "}, {"type": "image_url", "image_url": {}}]},
        ]
    }
    assert last_user_message(multimodal) == "second"
    assert last_user_message({"messages": [{"role": "assistant", "content": "x"}]}) == ""
    assert last_user_message({}) == ""
