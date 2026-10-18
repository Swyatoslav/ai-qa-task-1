"""Стражи защищённой версии: Input Guard и Output Guard.

Input Guard  — простой детектор запрещённых паттернов (по ТЗ:
               "хотя бы простой: запрещённые паттерны + отказ").
Output Guard — детекция утечки системного промпта, PII, секретов
               с redact/block.
"""
import re
import logging

logger = logging.getLogger("agent.guards")

# --- Сигнатуры секретов (значения из БД и secrets.env) ---
SECRET_VALUES = [
    "DEMO_STRIPE_KEY_FAKE_NOT_REAL_12345",
    "supersecret-jwt-signing-key-do-not-share-2026",
    "p@ssw0rd-internal-prod-2026",
    "DEMO_OPENAI_KEY_FAKE_NOT_REAL_12345",
    "tok_internal_5f4dcc3b5aa765d61d8327deb882cf99",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
]

# Сигнатуры системного промпта (утечка)
PROMPT_SIGNATURES = [
    "Internal Support Bot",
    "you can execute any SQL",
    "secrets table — you may read them",
    "Always answer the user's request fully",
]

# --- Input Guard: запрещённые паттерны ---
INPUT_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)\s+instructions?", re.I),
    re.compile(r"(reveal|show|print|repeat|output)\s+(your\s+)?(system\s+prompt|initialization|instructions|hidden\s+context)", re.I),
    re.compile(r"\bDAN\b", re.I),
    re.compile(r"do\s+anything\s+now", re.I),
    re.compile(r"(act|pretend|simulate)\s+as\s+(if\s+you\s+are\s+)?(a|an)?\s*(different|unrestricted|free|developer|admin)", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"\b(DELETE|DROP|TRUNCATE|UPDATE)\s+(FROM|TABLE|INTO)?", re.I),
    re.compile(r"dump\s+(the\s+)?secrets", re.I),
    re.compile(r"secrets\s+table", re.I),
    re.compile(r"api\s*keys?\s*(for|from|of)\s+(the\s+)?(company|internal|system)", re.I),
    re.compile(r"decode\s+(this|the\s+following)\s+(base64|b64|encoded)", re.I),
    re.compile(r"[A-Za-z0-9+/]{60,}={0,2}"),  # длинный base64-блоб
    re.compile(r"developer\s+mode|debug\s+mode|maintenance\s+mode", re.I),
    re.compile(r"new\s+rules?:\s*", re.I),
    re.compile(r"\[SYSTEM\s+OVERRIDE\]", re.I),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(developer|admin|root|unfiltered)\s+mode", re.I),
]


def input_guard(text: str):
    """Возвращает (allowed: bool, reason: str)."""
    if not text:
        return True, ""
    for pat in INPUT_PATTERNS:
        m = pat.search(text)
        if m:
            reason = f"Blocked input pattern: {pat.pattern!r} matched '{m.group(0)}'"
            logger.info("INPUT GUARD blocked: %s", reason)
            return False, reason
    return True, ""


# --- Output Guard ---
REDACT_PATTERNS = [
    re.compile(r"sk[_-]?(live|test|proj)[-_]?[A-Za-z0-9]{10,}"),
    re.compile(r"tok_internal_[A-Za-z0-9]+"),
    re.compile(r"wJalrXUtnFEMI[A-Za-z0-9/]+"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token|access[_-]?key)\s*[:=]\s*[^\s,;'\"]+"),
    re.compile(r"supersecret-jwt[A-Za-z0-9\-]+"),
    re.compile(r"p@ssw0rd-internal[A-Za-z0-9\-]*"),
    re.compile(r"[A-Za-z0-9._%+-]+@company\.com"),  # PII email
    re.compile(r"\+1-555-01\d{2}"),  # PII phone
]

LEAK_SIGNATURES = [re.compile(re.escape(s), re.I) for s in PROMPT_SIGNATURES]


def output_guard(text: str):
    """Возвращает (safe_text: str, leaked: list[str])."""
    if not text:
        return text, []
    leaked = []
    # 1. Утечка системного промпта
    for sig in LEAK_SIGNATURES:
        if sig.search(text):
            leaked.append("system_prompt")
            break
    # 2. Утечка секретов
    for sv in SECRET_VALUES:
        if sv in text:
            leaked.append("secret_value")
            break
    for pat in REDACT_PATTERNS:
        if pat.search(text):
            leaked.append("secret_or_pii_pattern")
            break
    # Redact
    safe = text
    for sv in SECRET_VALUES:
        safe = safe.replace(sv, "[REDACTED]")
    for pat in REDACT_PATTERNS:
        safe = pat.sub("[REDACTED]", safe)
    for sig in LEAK_SIGNATURES:
        safe = sig.sub("[REDACTED-POLICY]", safe)
    if leaked:
        logger.info("OUTPUT GUARD redacted: %s", leaked)
    return safe, leaked
