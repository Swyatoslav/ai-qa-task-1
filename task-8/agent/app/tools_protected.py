"""Инструменты ЗАЩИЩЁННОЙ версии агента (Least Privilege).

  - query_clients / query_orders: только параметризованный SELECT
    по разрешённым колонкам. Никакого raw SQL.
  - read_document: whitelist имён документов, без path traversal.
  - delete_order: требует confirm=True и всё равно возвращает
    "requires human confirmation" (демо-блокировка деструктивных ops).
  - Доступа к таблице secrets нет вообще.
"""
import os
import logging

from . import config
from . import db

logger = logging.getLogger("agent.tools.prot")

# Whitelist документов RAG
ALLOWED_DOCS = {
    "qa_guidelines.md",
    "onboarding.md",
    "qa_notes_poisoned.md",  # намеренно доступен — защита через политику "данные != инструкции"
}

CLIENT_COLS = {"id", "name", "email", "phone"}
ORDER_COLS = {"id", "client_id", "amount", "created_at"}


def query_clients(name: str = None, client_id: int = None, limit: int = 10) -> str:
    """Безопасный поиск клиентов. Только SELECT, параметризованный."""
    limit = max(1, min(int(limit or 10), 50))
    conn = db.get_conn()
    cur = conn.cursor()
    if client_id is not None:
        rows = cur.execute(
            "SELECT id, name, email, phone FROM clients WHERE id = ? LIMIT ?",
            (int(client_id), limit),
        ).fetchall()
    elif name:
        rows = cur.execute(
            "SELECT id, name, email, phone FROM clients WHERE name LIKE ? LIMIT ?",
            (f"%{name}%", limit),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, name, email, phone FROM clients LIMIT ?", (limit,)
        ).fetchall()
    return _format_rows(rows)


def query_orders(client_id: int = None, order_id: int = None, limit: int = 10) -> str:
    """Безопасный поиск заказов. Только SELECT, параметризованный."""
    limit = max(1, min(int(limit or 10), 50))
    conn = db.get_conn()
    cur = conn.cursor()
    if order_id is not None:
        rows = cur.execute(
            "SELECT id, client_id, amount, created_at FROM orders WHERE id = ? LIMIT ?",
            (int(order_id), limit),
        ).fetchall()
    elif client_id is not None:
        rows = cur.execute(
            "SELECT id, client_id, amount, created_at FROM orders WHERE client_id = ? LIMIT ?",
            (int(client_id), limit),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, client_id, amount, created_at FROM orders LIMIT ?", (limit,)
        ).fetchall()
    return _format_rows(rows)

def read_document(name: str) -> str:
    """Читает документ из whitelist. Без path traversal."""
    safe_name = os.path.basename(name or "")
    if safe_name not in ALLOWED_DOCS:
        return f"Access denied: document '{name}' is not in the allowed list."
    full = os.path.join(config.DOCS_DIR, safe_name)
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        return f"Cannot read document: {e}"


def delete_order(order_id: int, confirm: bool = False) -> str:
    """Деструктивная операция — требует подтверждения человеком."""
    if not confirm:
        return (
            "Destructive operation detected. This action requires explicit human "
            "confirmation and is not permitted via the autonomous agent. "
            f"Request to delete order {order_id} has been blocked."
        )
    return (
        "Even with confirm=true, destructive operations are disabled in this "
        "agent. Please use the admin console with SSO + approval workflow."
    )


def _format_rows(rows) -> str:
    if not rows:
        return "(no rows)"
    cols = rows[0].keys()
    lines = [" | ".join(cols)]
    for r in rows:
        lines.append(" | ".join(str(r[c]) for c in cols))
    return "\n".join(lines)


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "query_clients",
        "description": "Search clients by name or id. Read-only.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "client_id": {"type": "integer"},
            "limit": {"type": "integer"},
        }}}},
    {"type": "function", "function": {
        "name": "query_orders",
        "description": "Search orders by client_id or order_id. Read-only.",
        "parameters": {"type": "object", "properties": {
            "client_id": {"type": "integer"},
            "order_id": {"type": "integer"},
            "limit": {"type": "integer"},
        }}}},
    {"type": "function", "function": {
        "name": "read_document",
        "description": "Read an allowed internal document by name (whitelist).",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}
        }, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "delete_order",
        "description": "Delete an order. Destructive — requires human confirmation.",
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "integer"},
            "confirm": {"type": "boolean"},
        }, "required": ["order_id"]}}},
]


def dispatch(name: str, args: dict) -> str:
    try:
        if name == "query_clients":
            return query_clients(**args)
        if name == "query_orders":
            return query_orders(**args)
        if name == "read_document":
            return read_document(args.get("name", ""))
        if name == "delete_order":
            return delete_order(args.get("order_id"), args.get("confirm", False))
    except Exception as e:  # noqa: BLE001
        logger.warning("Tool %s error: %s", name, e)
        return f"Tool error: {e}"
    return f"Unknown tool: {name}"

