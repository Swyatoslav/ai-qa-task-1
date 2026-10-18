# Task 8 — Уязвимый и защищённый LLM-агент: red-team, защита, автоматизация

Исследовательская работа по безопасности LLM-агентов: поднимается уязвимый
агент с избыточными правами, проводится ручной red-team (6 классов атак),
агент защищается (prompt isolation, least privilege, input/output guards),
защита проверяется автоматизированным прогоном (22 payload'а, отчёт JSON/HTML/MD).

## Архитектура

```
Ollama (qwen2.5:7b)  ──OpenAI-compatible API──>  FastAPI агент
                                                    ├── AGENT_MODE=vulnerable  (:8001)
                                                    └── AGENT_MODE=protected   (:8002)
Инструменты:
  vulnerable: run_sql (ANY SQL, incl. DELETE/DROP, reads secrets) + read_document (path traversal)
  protected:  query_clients/query_orders (parameterized SELECT) + read_document (whitelist)
              + delete_order (blocked, human confirmation) + input/output guards
```

## Быстрый старт (одна команда)

```bash
docker compose up --build
```

Поднимает:
- **Ollama** (порт 11434) + авто-pull модели `qwen2.5:7b`.
- **agent-vulnerable** (порт 8001) — уязвимая версия.
- **agent-protected** (порт 8002) — защищённая версия.

> Первый запуск скачивает модель (~4.7 ГБ). Без GPU используется CPU —
> инференс медленнее, но работает. Для GPU раскомментируйте блок
> `deploy.resources` в `docker-compose.yml` (нужен NVIDIA Container Toolkit).

Проверка:
```bash
curl http://localhost:8001/health   # {"status":"ok","mode":"vulnerable",...}
curl http://localhost:8002/health   # {"status":"ok","mode":"protected",...}
```

Пример запроса:
```bash
curl -X POST http://localhost:8001/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What orders does Alice have?"}'
```

## Автоматизированный прогон атак (одна команда)

После `docker compose up --build` в отдельном терминале:

```bash
cd tests && python3 run_tests.py
```

Генерирует отчёты в `tests/reports/`:
- `report.json` — машиночитаемый.
- `report.md`  — Markdown с детализацией по каждому payload.
- `report.html` — HTML-таблица с цветовой индикацией.

Альтернатива (pytest, для CI):
```bash
pip install -r tests/requirements.txt
pytest tests/test_attacks.py -v
```

Эталонный отчёт последнего прогона уже лежит в `tests/reports/`
(22/22 атак прошли на уязвимой версии, 22/22 заблокированы на защищённой).

## Структура

```
task-8/
├── docker-compose.yml          # Ollama + agent-vulnerable + agent-protected
├── REPORT.md                   # основной отчёт по структуре задания
├── README.md                   # этот файл
├── agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI: POST /chat, GET /health
│       ├── agent.py            # цикл LLM + tool-calling
│       ├── llm.py              # Ollama-клиент (openai SDK)
│       ├── db.py               # SQLite: clients, orders, secrets
│       ├── tools_vulnerable.py # избыточные права
│       ├── tools_protected.py  # least privilege
│       ├── guards.py           # input/output guard
│       ├── policy.py           # системные промпты (слабый / изолированный)
│       └── data/internal_docs/ # RAG-документы (включая отравленный)
└── tests/
    ├── payloads.py             # 22 payload'а, 6 классов
    ├── judges.py               # regex-детекторы
    ├── run_tests.py            # runner + генерация отчёта
    ├── test_attacks.py         # pytest-версия
    ├── generate_report.py      # генерация эталонного отчёта
    └── reports/                # report.json, report.md, report.html
```

## Модель

По умолчанию `qwen2.5:7b` (хорошая поддержка tool-calling в Ollama).
Сменить через `MODEL=qwen2.5:3b` (легче) или `MODEL=llama3.1:8b`.
Не забудьте обновить `command` в сервисе `ollama-init`.
