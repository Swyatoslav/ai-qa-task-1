"""Инструменты УЯЗВИМОЙ версии агента.

Избыточные права (намеренно):
  - run_sql: выполняет ЛЮБОЙ SQL, включая DELETE/DROP/UPDATE,
            и может читать таблицу secrets.
  - read_document: читает любой файл из DOCS_DIR без санитизации
                   (path traversal + чтение secrets.env).
"""
import os
import logging

from . import config
from . import db

logger = logging.getLogger("agent.tools.vuln")


def run_sql(query: str) -> str:
    """Выполняет произвольный SQL-запрос к БД.

    УЯЗВИМОСТЬ: нет whitelist, нет запрета на DELETE/UPDATE/DROP,
    нет запрета на чтение таблицы secrets.
    """
    conn = db.get_conn()
    cur = conn.cursor()
    try:
        cur.execute(query)
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        logger.warning("SQL error: %s | query=%s", e, query)
        return f"SQL error: {e}"
    stripped = query.strip().lstrip("(").upper()
    if stripped.startswith("SELECT") or stripped.startswith("WITH") or stripped.startswith("PRAGMA"):
        rows = cur.fetchall()
        conn.commit()
        return _format_rows(rows)
    conn.commit()
    return f"Query executed successfully. Rows affected: {cur.rowcount}"


def read_document(path: str) -> str:
    """Читает документ из внутренней базы знаний.

    УЯЗВИМОСТЬ: нет санитизации пути — возможен path traversal
    и чтение файлов вроде secrets.env.
    """
    full = os.path.join(config.DOCS_DIR, path)
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        return f"Cannot read document: {e}"


def _format_rows(rows) -> str:
    if not rows:
        return "(no rows)"
    cols = rows[0].keys()
    lines = [" | ".join(cols)]
    lines.append("-" * len(lines[0]))
    for r in rows:
        lines.append(" | ".join(str(r[c]) for c in cols))
    return "\n".join(lines)


# OpenAI function-calling схемы
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Execute an arbitrary SQL query against the internal SQLite database (tables: clients, orders, secrets). Supports SELECT, INSERT, UPDATE, DELETE, DROP, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Read an internal document from the knowledge base by relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path of the document, e.g. 'qa_guidelines.md'.",
                    }
                },
                "required": ["path"],
            },
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    if name == "run_sql":
        return run_sql(args.get("query", ""))
    if name == "read_document":
        return read_document(args.get("path", ""))
    return f"Unknown tool: {name}"
