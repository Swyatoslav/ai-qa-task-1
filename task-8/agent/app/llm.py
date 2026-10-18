"""LLM-клиент — Ollama через OpenAI-compatible API.

Используется библиотека openai, совместимая с эндпоинтом Ollama /v1.
Нативные tool-calls (function calling) поддерживаются моделями qwen2.5/llama3.1.
"""
import logging

from openai import OpenAI

from . import config

logger = logging.getLogger("agent.llm")

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=config.OLLAMA_BASE_URL,
            api_key=config.OLLAMA_API_KEY,
        )
    return _client


def chat_completion(messages, tools=None, tool_choice=None):
    """Вызов chat completion с опциональными инструментами.

    Возвращает объект response (openai). Температура подобрана для
    воспроизводимости red-team-демо.
    """
    kwargs = {
        "model": config.MODEL,
        "messages": messages,
        "temperature": 0.7,
    }
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

    logger.debug("LLM request: model=%s msgs=%d tools=%d",
                 config.MODEL, len(messages), len(tools or []))
    resp = get_client().chat.completions.create(**kwargs)
    return resp


def ensure_model():
    """Проверяет доступность модели, делая пробный запрос."""
    try:
        get_client().models.list()
        logger.info("Ollama endpoint reachable at %s", config.OLLAMA_BASE_URL)
    except Exception as e:  # noqa: BLE001
        logger.warning("Ollama not ready yet: %s", e)
