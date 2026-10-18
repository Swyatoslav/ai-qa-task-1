"""Генерация эталонного отчёта автоматизации.

Запускает все red-team payloads против живых агентов (qwen2.5:7b через Ollama)
и генерирует отчёт: reports/report.json, report.md, report.html.

Запуск: python tests/generate_report.py
(требует запущенные агенты: docker compose up --build)

Эквивалентно run_tests.py — выделено в отдельный скрипт для удобства
запуска из CI-пайплайна.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import run_tests  # noqa: E402


if __name__ == "__main__":
    summary = run_tests.run_suite()
    sys.exit(0 if summary["prot_blocked"] == summary["total"] else 1)

