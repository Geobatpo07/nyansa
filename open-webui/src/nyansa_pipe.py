"""
title: Nyansa
description: Answers from your Obsidian notes through the n8n chat workflow, citing the notes it used.
version: 0.1.0
license: Apache-2.0
"""

# Open WebUI function of type "pipe": paste this file in Admin Panel >
# Functions, then set WEBHOOK_TOKEN in its valves (N8N_WEBHOOK_TOKEN of .env).
# It appears as a model named after the function. Open WebUI runs it in its
# own process, so it only uses libraries Open WebUI already ships.

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

# Open WebUI runs Python 3.11: no `type` statement.
EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]


class Pipe:
    class Valves(BaseModel):
        N8N_CHAT_URL: str = Field(
            default="http://nyansa-n8n:5678/webhook/nyansa-chat",
            description="Chat webhook of n8n, on the internal Docker network.",
        )
        WEBHOOK_TOKEN: str = Field(
            default="",
            description="N8N_WEBHOOK_TOKEN from .env, sent in the X-Nyansa-Token header.",
            json_schema_extra={"input": {"type": "password"}},
        )
        TIMEOUT_SECONDS: int = Field(default=300, description="A CPU-only server can take a minute or two to answer.")

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def pipe(self, body: dict[str, Any], __event_emitter__: EventEmitter | None = None) -> str:
        question = last_user_message(body)
        if not question:
            return "Pose une question sur tes notes."
        if not self.valves.WEBHOOK_TOKEN:
            return "Nyansa n'est pas configuré : renseigne WEBHOOK_TOKEN dans les valves de la fonction."

        await emit(__event_emitter__, {"type": "status", "data": {"description": "Recherche dans tes notes…"}})
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    self.valves.N8N_CHAT_URL,
                    json={"question": question},
                    headers={"X-Nyansa-Token": self.valves.WEBHOOK_TOKEN},
                )
        except httpx.HTTPError as err:
            await emit(__event_emitter__, {"type": "status", "data": {"description": "", "done": True}})
            return f"Nyansa est injoignable : {type(err).__name__} {err}".strip()
        await emit(__event_emitter__, {"type": "status", "data": {"description": "", "done": True}})

        if response.status_code == 403:
            return "n8n refuse le jeton : vérifie WEBHOOK_TOKEN dans les valves de la fonction."
        if response.status_code != 200:
            return f"n8n a répondu HTTP {response.status_code} : {response.text[:300]}"
        try:
            answer = response.json()
            text, sources = str(answer["answer"]), list(answer.get("sources", []))
        except (ValueError, KeyError, TypeError):
            return f"Réponse inattendue de n8n : {response.text[:300]}"

        for source in sources:
            await emit(__event_emitter__, {"type": "citation", "data": citation(source)})
        return text


def last_user_message(body: dict[str, Any]) -> str:
    """Text of the last user message; images and other parts are ignored."""
    for message in reversed(body.get("messages", [])):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content if part.get("type") == "text")
        return str(content).strip()
    return ""


def citation(source: dict[str, Any]) -> dict[str, Any]:
    """An Open WebUI citation for one cited note: its number, title, path and sections."""
    sections = [section for section in source.get("sections", []) if section]
    return {
        "source": {"name": f"[{source.get('n')}] {source.get('title')}"},
        "document": ["\n".join(sections) or str(source.get("title"))],
        "metadata": [{"source": source.get("path")}],
    }


async def emit(emitter: EventEmitter | None, event: dict[str, Any]) -> None:
    if emitter is not None:
        await emitter(event)
