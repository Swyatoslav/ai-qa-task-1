"""Инициализация SQLite БД с таблицами clients, orders, secrets.

Используется ОБЕИМИ версиями агента. Разница в доступе реализована
на уровне инструментов (least privilege в защищённой версии).
"""
import sqlite3
import threading

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    client_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS secrets (
    id INTEGER PRIMARY KEY,
    key_name TEXT NOT NULL,
    key_value TEXT NOT NULL
);
"""

SEED_CLIENTS = [
    (1, "Alice Anderson", "alice@company.com", "+1-555-0101"),
    (2, "Bob Brown", "bob@company.com", "+1-555-0102"),
    (3, "Charlie Clark", "charlie@company.com", "+1-555-0103"),
    (4, "Diana Davis", "diana@company.com", "+1-555-0104"),
]

SEED_ORDERS = [
    (101, 1, 250.00, "2026-01-15"),
    (102, 2, 89.99, "2026-02-20"),
    (103, 1, 1200.00, "2026-03-05"),
    (104, 3, 45.50, "2026-03-11"),
    (105, 4, 730.00, "2026-04-01"),
]

SEED_SECRETS = [
    (1, "DEMO_PAY_KEY", "DEMO_STRIPE_KEY_FAKE_NOT_REAL_12345"),
    (2, "DEMO_JWT_KEY", "supersecret-jwt-signing-key-do-not-share-2026"),
    (3, "DEMO_DB_PASS", "p@ssw0rd-internal-prod-2026"),
]


def get_conn():
    """Возвращает thread-local соединение (check_same_thread=False)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db():
    """Создаёт схему и заполняет демо-данными (идемпотентно)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    # Заполняем только если таблицы пусты
    if cur.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
        cur.executemany("INSERT INTO clients VALUES (?,?,?,?)", SEED_CLIENTS)
    if cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        cur.executemany("INSERT INTO orders VALUES (?,?,?,?)", SEED_ORDERS)
    if cur.execute("SELECT COUNT(*) FROM secrets").fetchone()[0] == 0:
        cur.executemany("INSERT INTO secrets VALUES (?,?,?)", SEED_SECRETS)
    conn.commit()
