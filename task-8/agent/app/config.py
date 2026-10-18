"""Конфигурация агента.

Переключение между уязвимой и защищённой версией осуществляется
переменной окружения AGENT_MODE (vulnerable | protected).
LLM-бэкенд — Ollama (OpenAI-compatible API).
"""
import os

AGENT_MODE = os.getenv("AGENT_MODE", "vulnerable").lower()

# Ollama (OpenAI-compatible endpoint)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
MODEL = os.getenv("MODEL", "qwen2.5:7b")

# БД
DB_PATH = os.getenv("DB_PATH", "/app/data/agent.db")

# Документы RAG
DOCS_DIR = os.path.join(os.path.dirname(__file__), "data", "internal_docs")

# Лимиты
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "6"))
