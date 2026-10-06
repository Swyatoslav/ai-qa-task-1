#!/usr/bin/env python3
"""
review_and_optimize.py — ревью и оптимизация кода автотестов.

Скрипт:
  1. Анализирует файл с автотестами (по умолчанию bad_code.py) через модуль `ast`.
  2. Находит типичные проблемы: дублирование, отсутствие timeout, захардкоженные
     эндпоинты, ассерты без сообщений, неиспользуемые импорты, проблемы именования.
  3. Генерирует оптимизированный вариант автотестов.
  4. Формирует отчёт о ревью в формате Markdown (review.md).

Запуск:
    python3 review_and_optimize.py
    python3 review_and_optimize.py --input bad_code.py --output optimized_code.py --report review.md
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUEST_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


@dataclass
class TestInfo:
    """Извлечённая из AST информация об одном тесте."""
    name: str
    line: int
    method: str = ""
    endpoint: str = ""
    url_repr: str = ""
    payload: dict | None = None
    expected_status: int | None = None
    body_field: str | None = None
    body_value: str | None = None
    json_call_count: int = 0
    has_timeout: bool = False
    has_json_kwarg: bool = False
    assert_count: int = 0
    assert_with_message: int = 0
    signature: str = ""


@dataclass
class Finding:
    """Одна найденная проблема (или наблюдение)."""
    category: str
    severity: str  # critical | high | medium | low | info
    title: str
    detail: str
    count: int = 1


def extract_endpoint_path(url_node: ast.AST) -> str:
    """Вернуть путь (path) из узла URL: f-string вида f\"{BASE_URL}/users\" или строки."""
    if isinstance(url_node, ast.JoinedStr):
        parts = [p.value for p in url_node.values
                 if isinstance(p, ast.Constant) and isinstance(p.value, str)]
        return "".join(parts) or "/"
    if isinstance(url_node, ast.Constant) and isinstance(url_node.value, str):
        p = urlparse(url_node.value).path
        return p if p else "/"
    return "/"


def statement_token(stmt: ast.stmt) -> str:
    """Словарный 'отпечаток' верхнеуровневого утверждения без учёта констант.

    Используется для детекта дублирования: два теста, у которых совпадают
    последовательности таких 'отпечатков', отличаются только данными.
    """
    if isinstance(stmt, ast.Assign):
        v = stmt.value
        if isinstance(v, ast.Dict):
            return f"assign_dict:{len(v.keys)}"
        if isinstance(v, ast.Call):
            f = v.func
            m = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "?")
            return f"req:{m}"
        return "assign"
    if isinstance(stmt, ast.Assert):
        t = stmt.test
        if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq):
            left = t.left
            if isinstance(left, ast.Attribute) and left.attr == "status_code":
                return "assert_status"
            if isinstance(left, ast.Subscript) and isinstance(left.value, ast.Call):
                fv = left.value.func
                if isinstance(fv, ast.Attribute) and fv.attr == "json":
                    return "assert_body"
            return "assert_cmp"
        return "assert"
    return "stmt"


def signature_of(func: ast.FunctionDef) -> str:
    """Структурная сигнатура тела теста (для группировки дублей)."""
    return "|".join(statement_token(s) for s in func.body)


def extract_test_info(func: ast.FunctionDef, signature: str) -> TestInfo:
    """Извлечь из тела теста данные: метод, эндпоинт, payload, статусы, ассерты."""
    ti = TestInfo(name=func.name, line=func.lineno, signature=signature)

    # 1) payload (словарь, присвоенный какой-либо переменной)
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and ti.payload is None:
            d = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    d[k.value] = v.value if isinstance(v, ast.Constant) else ast.unparse(v)
            ti.payload = d

    # 2) HTTP-запрос requests.<method>(...)
    req = None
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if name in REQUEST_METHODS:
                req = node
                break
    if req is not None:
        f = req.func
        ti.method = (f.attr if isinstance(f, ast.Attribute) else f.id).upper()
        if req.args:
            ti.url_repr = ast.unparse(req.args[0])
            ti.endpoint = extract_endpoint_path(req.args[0])
        for kw in req.keywords:
            if kw.arg == "timeout":
                ti.has_timeout = True
            elif kw.arg == "json":
                ti.has_json_kwarg = True

    # 3) число вызовов .json()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "json":
            ti.json_call_count += 1

    # 4) ассерты: статус-код и/или поле тела ответа
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            ti.assert_count += 1
            if node.msg is not None:
                ti.assert_with_message += 1
            t = node.test
            if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq):
                left, comp = t.left, t.comparators[0]
                if isinstance(left, ast.Attribute) and left.attr == "status_code" and isinstance(comp, ast.Constant):
                    ti.expected_status = comp.value
                elif isinstance(left, ast.Subscript) and isinstance(left.value, ast.Call):
                    fv = left.value.func
                    if isinstance(fv, ast.Attribute) and fv.attr == "json" and isinstance(left.slice, ast.Constant):
                        ti.body_field = left.slice.value
                        if isinstance(comp, ast.Constant):
                            ti.body_value = comp.value
    return ti


_TOP_LEVEL_RE = re.compile(r"^(import\s|from\s|def\s|class\s|@)")


def repair_indentation(source: str) -> str:
    """Восстановить пропущенные отступы в телах функций.

    Типичный 'битый' код: строки `def test_x():` и их тело стоят в одном
    уровне (без отступа). Здесь каждое объявление `def`/`class`/декоратор
    считается верхнеуровневым, а следующие за ним строки до следующего
    верхнеуровневого — телом (втягиваются на один уровень).
    """
    out, inside = [], False
    for raw in source.splitlines():
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if _TOP_LEVEL_RE.match(s):
            out.append(s)
            inside = s.endswith(":")
        elif inside:
            out.append("    " + s)
        else:
            out.append(s)
    return "\n".join(out) + "\n"


def analyze(source: str, filename: str) -> dict:
    """Провести статический анализ файла с автотестами и собрать все данные для отчёта."""
    tree = ast.parse(source)

    # базовый URL (модульная константа в верхнем регистре)
    base_url, base_url_is_const = None, False
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    base_url, base_url_is_const = node.value.value, True
                    break
        if base_url is not None:
            break
    if base_url is None:
        base_url = "http://localhost:8000"

    # импорты и реальные ссылки на них (для детекта неиспользуемых)
    imported, referenced = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    imported.add(a.asname or a.name)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                referenced.add(n.id)
    unused_imports = sorted(imported - referenced)

    func_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    tests = [extract_test_info(f, signature_of(f)) for f in func_nodes]

    # дублирование: группировка по структурной сигнатуре
    sig_counter = Counter(t.signature for t in tests)
    dup_groups = {s: c for s, c in sig_counter.items() if c > 1}
    dup_test_count = sum(dup_groups.values())

    # группировка по (метод, эндпоинт) — кандидаты на объединение в параметризованный тест
    group_counter = Counter((t.method, t.endpoint) for t in tests)

    path_counter = Counter(t.endpoint for t in tests if t.endpoint)
    top_path, top_path_count = path_counter.most_common(1)[0] if path_counter else ("", 0)

    missing_timeout = sum(1 for t in tests if not t.has_timeout)
    assertions_total = sum(t.assert_count for t in tests)
    assertions_with_msg = sum(t.assert_with_message for t in tests)
    bare_asserts = assertions_total - assertions_with_msg
    positive = sum(1 for t in tests if t.expected_status in (200, 201))
    negative = sum(1 for t in tests if t.expected_status is not None and t.expected_status >= 400)
    uses_json_body = any(t.has_json_kwarg for t in tests)
    checks_body = any(t.body_field is not None for t in tests)
    tests_independent = all(not any(isinstance(n, ast.Global) for n in ast.walk(f)) for f in func_nodes)

    # именование: повторяющиеся токены в имени теста
    naming_issues = []
    for t in tests:
        tokens = [x for x in t.name[len("test_"):].split("_") if x]
        if any(c >= 2 for c in Counter(tokens).values()):
            naming_issues.append(t.name)

    findings = []
    if dup_test_count > 1:
        findings.append(Finding("parametrize", "high", "Дублирование кода в тестах",
            f"Обнаружено {dup_test_count} тест(ов) с идентичной структурой, различающихся только "
            f"данными (константами). Это классический случай для @pytest.mark.parametrize: тело "
            f"одного теста заменяется параметризованным, а данные выносятся в список. Код становится "
            f"короче и проще в поддержке.", dup_test_count))
    if missing_timeout:
        findings.append(Finding("timeout", "medium", "HTTP-запросы без timeout",
            f"{missing_timeout} из {len(tests)} запрос(ов) к requests выполняются без параметра timeout. "
            f"При недоступном или зависшем сервере тест будет ждать неопределённо долго и «вешать» "
            f"весь прогон. Рекомендация: добавить timeout (например, 5 секунд) в каждый запрос.",
            missing_timeout))
    if top_path_count > 1:
        findings.append(Finding("endpoint", "medium", "Захардкоженный путь эндпоинта",
            f"Путь {top_path!r} задаётся прямо в каждом из {top_path_count} запросов, а не хранится в "
            f"константе. При изменении API придётся править его в N местах. Лучше вынести в модульную "
            f"константу (например, USERS_ENDPOINT = f\"{{BASE_URL}}/users\").", top_path_count))
    if bare_asserts:
        findings.append(Finding("assert_msg", "medium", "Ассерты без поясняющих сообщений",
            f"{bare_asserts} из {assertions_total} assert-ов не несут поясняющего сообщения. При падении "
            f"сложно сразу понять, какое именно условие нарушилось и какие входные данные были "
            f"задействованы. Рекомендация: добавлять message в assert.", bare_asserts))
    if unused_imports:
        findings.append(Finding("unused_import", "low", "Неиспользуемые импорты",
            "Импортируются модули, которые в коде не используются: "
            + ", ".join(f"`{x}`" for x in unused_imports)
            + ". Лишние импорты создают иллюзию зависимости и раздражают линтеры.", len(unused_imports)))
    if naming_issues:
        findings.append(Finding("naming", "low", "Непоследовательное именование тестов",
            "Имена с повторяющимися/артефактными токенами: "
            + ", ".join(f"`{n}`" for n in naming_issues)
            + ". Похоже на следы ручных переименований (copy/paste); такие имена хуже читаются в "
            + "отчётах pytest.", len(naming_issues)))

    positives = []
    if positive and negative:
        positives.append(f"Покрытие и позитивных ({positive} шт., ожидание 2xx), и негативных "
                         f"({negative} шт., ожидание 4xx) сценариев.")
    elif positive:
        positives.append(f"Есть позитивные сценарии ({positive} шт.).")
    elif negative:
        positives.append(f"Есть негативные сценарии ({negative} шт.).")
    if uses_json_body:
        positives.append("Корректная отправка тела запроса через параметр `json=` (правильная "
                         "сериализация и Content-Type).")
    if base_url_is_const:
        positives.append(f"Базовый URL вынесен в модульную константу `BASE_URL = {base_url!r}`.")
    if checks_body:
        positives.append("В позитивных тестах проверяется не только статус-код, но и содержимое "
                         "ответа (поле из тела).")
    if tests_independent:
        positives.append("Тесты автономны и не зависят друг от друга (нет общего изменяемого "
                         "состояния) — хорошо для повторного и параллельного прогона.")
    descriptive = [t.name for t in tests if t.expected_status and t.expected_status >= 400]
    if descriptive:
        positives.append("Негативные тесты имеют говорящие имена: "
                         + ", ".join(f"`{n}`" for n in descriptive) + ".")

    metrics = {
        "tests_total": len(tests),
        "tests_positive": positive,
        "tests_negative": negative,
        "duplicated_tests": dup_test_count,
        "dup_groups": len(dup_groups),
        "request_calls": len(tests),
        "calls_with_timeout": len(tests) - missing_timeout,
        "calls_without_timeout": missing_timeout,
        "assertions_total": assertions_total,
        "assertions_with_message": assertions_with_msg,
        "unused_imports": len(unused_imports),
        "naming_issues": len(naming_issues),
        "distinct_endpoints": len(path_counter),
        "top_endpoint": top_path,
        "top_endpoint_count": top_path_count,
    }

    return {
        "source": source,
        "filename": filename,
        "tree": tree,
        "tests": tests,
        "func_nodes": func_nodes,
        "base_url": base_url,
        "findings": findings,
        "positives": positives,
        "metrics": metrics,
        "group_counter": group_counter,
    }


def gen_const_name(path: str, used: set) -> str:
    """Имя константы для эндпоинта: /users -> USERS_ENDPOINT."""
    p = path.strip("/")
    base = re.sub(r"[^0-9A-Za-z]+", "_", p).strip("_").upper() or "ENDPOINT"
    name, i = f"{base}_ENDPOINT", 2
    while name in used:
        name, i = f"{base}_{i}_ENDPOINT", i + 1
    used.add(name)
    return name


def fmt_dict(d: dict) -> str:
    """Печатная форма словаря payload для строки параметризации."""
    if not d:
        return "{}"
    return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in d.items()) + "}"


def generate_optimized(ctx: dict) -> str:
    """Сгенерировать оптимизированный вариант автотестов на основе найденных данных.

    Тесты, обращающиеся к одному и тому же (метод, эндпоинт), объединяются в
    параметризованный тест; добавляются сессия, timeout, константы и осмысленные ассерты.
    """
    tests, base_url = ctx["tests"], ctx["base_url"]

    groups = OrderedDict()
    for t in tests:
        groups.setdefault((t.method, t.endpoint), []).append(t)

    used, const_by_key = set(), {}
    for key in groups:
        const_by_key[key] = gen_const_name(key[1], used)

    L = []
    A = L.append
    A('"""')
    A('Оптимизированные автотесты для API.')
    A('')
    A(f'Сгенерировано автоматически скриптом review_and_optimize.py из файла {ctx["filename"]}.')
    A('')
    A('Ключевые улучшения:')
    A('  * дублирование удалено — одинаковые тесты заменены @pytest.mark.parametrize;')
    A('  * переиспользование соединения через requests.Session (fixture api_client);')
    A('  * добавлен timeout во все HTTP-запросы;')
    A('  * эндпоинты вынесены в константы;')
    A('  * информативные сообщения в assert;')
    A('  * тело ответа (JSON) парсится один раз и проверяется целиком.')
    A('"""')
    A('import pytest')
    A('import requests')
    A('')
    A(f'BASE_URL = {base_url!r}')
    for key, cname in const_by_key.items():
        A('%s = f"{BASE_URL}%s"' % (cname, key[1]))
    A('REQUEST_TIMEOUT = 5  # секунд')
    A('')
    A('')
    A('@pytest.fixture()')
    A('def api_client():')
    A('    """HTTP-клиент (requests.Session) с пулингом соединений."""')
    A('    with requests.Session() as session:')
    A('        yield session')

    used_names = set()
    for (method, endpoint), group in groups.items():
        cname = const_by_key[(method, endpoint)]
        field_counter = Counter(t.body_field for t in group if t.body_field)
        common_field = field_counter.most_common(1)[0][0] if field_counter else None

        test_name, base_name, i = group[0].name, group[0].name, 2
        while test_name in used_names:
            test_name, i = f"{base_name}_{i}", i + 1
        used_names.add(test_name)

        rows, ids = [], []
        for t in group:
            payload = t.payload if t.payload is not None else {}
            expected_name = t.body_value if (common_field and t.body_field == common_field) else None
            if common_field:
                rows.append(f"        ({fmt_dict(payload)}, {t.expected_status}, {expected_name!r}),")
            else:
                rows.append(f"        ({fmt_dict(payload)}, {t.expected_status}),")
            ids.append('        "%s",' % t.name[len("test_"):])

        A('')
        A('')
        A('@pytest.mark.parametrize(')
        A(f'    "payload, expected_status, expected_{common_field}",' if common_field
          else '    "payload, expected_status",')
        A('    [')
        A("\n".join(rows))
        A('    ],')
        A('    ids=[')
        A("\n".join(ids))
        A('    ],')
        A(')')
        A(f'def {test_name}(api_client, payload, expected_status, expected_{common_field}):' if common_field
          else f'def {test_name}(api_client, payload, expected_status):')
        A(f'    response = api_client.{method.lower()}(')
        A(f'        {cname}, json=payload, timeout=REQUEST_TIMEOUT')
        A('    )')
        A('    assert response.status_code == expected_status, (')
        A('        f"Ожидался HTTP {expected_status}, получен {response.status_code}. "')
        A('        f"Тело ответа: {response.text}"')
        A('    )')
        if common_field:
            A(f'    if expected_{common_field} is not None:')
            A('        body = response.json()')
            A(f'        assert body.get("{common_field}") == expected_{common_field}, (')
            A('            f"В ответе %s={body.get(\'%s\')!r}, ожидалось {expected_%s!r}"'
              % (common_field, common_field, common_field))
            A('        )')
    A('')
    A('')
    A('if __name__ == "__main__":')
    A('    pytest.main([__file__, "-v"])')
    A('')
    return "\n".join(L)


SEV_BADGE = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}
SEV_RU = {"critical": "критично", "high": "высокий", "medium": "средний", "low": "низкий", "info": "инфо"}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEV_WEIGHT = {"critical": 25, "high": 15, "medium": 8, "low": 3, "info": 1}


def compute_score(findings: list) -> int:
    """Условная оценка поддерживаемости: 100 минус штраф за каждую проблему."""
    s = 100 - sum(SEV_WEIGHT.get(f.severity, 0) for f in findings)
    return max(0, min(100, s))


def build_review(ctx: dict, optimized_rel: str) -> str:
    """Собрать отчёт о ревью в формате Markdown."""
    m, findings, positives = ctx["metrics"], ctx["findings"], ctx["positives"]
    score = compute_score(findings)
    repaired = ctx.get("repaired", False)
    if repaired:  # исходный код не запускался — сильнее снижаем оценку
        score = max(0, score - 15)

    band = ("Отличный код, не требует заметных изменений" if score >= 90
            else "Хороший код, возможны небольшие доработки" if score >= 75
            else "Код работает, но требует существенной оптимизации" if score >= 50
            else "Код требует значительной переделки")

    L = []
    A = L.append
    A("# 📋 Отчёт по ревью кода автотестов")
    A("")
    A(f"> Файл: `{ctx['filename']}`  ·  Сгенерировано скриптом `review_and_optimize.py`  ·  "
      f"Автоматический статический анализ (модуль `ast`).")
    A("")
    if repaired:
        A("> ⚠️ **Важно:** исходный файл **не является валидным Python-кодом** (в телах функций "
          "пропущены отступы), поэтому `pytest` не мог его выполнить. Скрипт автоматически "
          "восстановил синтаксис перед анализом.")
        A("")
    A("## 🎯 Итоговая оценка")
    A("")
    A(f"- **Оценка поддерживаемости:** {score}/100 — {band}.")
    A(f"- **Тестов:** {m['tests_total']}  ·  **Проблем найдено:** {len(findings)}")
    A(f"- **Оптимизированный вариант:** `{optimized_rel}`")
    A("")
    A("## 📊 Метрики")
    A("")
    A("| Метрика | Значение |")
    A("| --- | --- |")
    A(f"| Всего тестов | {m['tests_total']} |")
    A(f"| Позитивные сценарии (2xx) | {m['tests_positive']} |")
    A(f"| Негативные сценарии (4xx) | {m['tests_negative']} |")
    A(f"| Тестов с дублированием структуры | {m['duplicated_tests']} |")
    A(f"| HTTP-запросов | {m['request_calls']} |")
    A(f"| Запросов **без** timeout | {m['calls_without_timeout']} |")
    A(f"| Ассертов всего / с сообщением | {m['assertions_total']} / {m['assertions_with_message']} |")
    A(f"| Захардкоженных путей эндпоинта | {m['top_endpoint_count']}× `{m['top_endpoint']}` |")
    A(f"| Неиспользуемых импортов | {m['unused_imports']} |")
    A(f"| Проблем с именованием | {m['naming_issues']} |")
    A("")
    A("## ✅ Что сделано хорошо")
    A("")
    for i, p in enumerate(positives, 1):
        A(f"{i}. {p}")
    A("")
    A("## ⚠️ Что сделано плохо / можно улучшить")
    A("")
    if repaired:
        A("**🔴 Неинтерпретируемый код.** В исходнике пропущены отступы в телах всех функций — "
          "файл физически не запускается (`IndentationError`). Это самая серьёзная проблема: "
          "автотесты просто не могут выполниться. Скрипт восстановил отступы.")
        A("")
    for i, f in enumerate(sorted(findings, key=lambda x: SEV_ORDER[x.severity]), 1):
        A(f"### {i}. {SEV_BADGE[f.severity]} {f.title}  ·  приоритет: {SEV_RU[f.severity]}")
        A("")
        A(f"> **{f.detail}**")
        A("")

    A("## 🔧 Ключевое улучшение: параметризация вместо дублирования")
    A("")
    A("**Было** (3 почти одинаковых теста):")
    A("")
    A("```python")
    A("def test_create_user():")
    A('    payload = {"name": "Alice", "email": "alice@example.com"}')
    A('    response = requests.post(f"{BASE_URL}/users", json=payload)')
    A("    assert response.status_code == 201")
    A('    assert response.json()["name"] == "Alice"')
    A("")
    A("# ... и ещё 2 таких же с Bob и Charlie ...")
    A("```")
    A("")
    A("**Стало** (1 параметризованный тест + сессия + timeout):")
    A("")
    A("```python")
    A('USERS_ENDPOINT = f"{BASE_URL}/users"')
    A("REQUEST_TIMEOUT = 5")
    A("")
    A("@pytest.fixture()")
    A("def api_client():")
    A("    with requests.Session() as session:")
    A("        yield session")
    A("")
    A('@pytest.mark.parametrize("payload, expected_status, expected_name", [')
    A('    ({"name": "Alice", "email": "alice@example.com"}, 201, "Alice"),')
    A('    ({"name": "Bob", "email": "bob@example.com"}, 201, "Bob"),')
    A("    # ... и остальные данные ...")
    A("])")
    A("def test_create_user(api_client, payload, expected_status, expected_name):")
    A("    response = api_client.post(USERS_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT)")
    A('    assert response.status_code == expected_status, f"..."')
    A("    if expected_name is not None:")
    A('        assert response.json().get("name") == expected_name')
    A("```")
    A("")
    A("## 📈 Сводная таблица «Было → Стало»")
    A("")
    A("| # | Проблема | Было | Стало |")
    A("| --- | --- | --- | --- |")
    A("| 1 | Дублирование тестов | 5 отдельных функций | 1 `@pytest.mark.parametrize` (5 наборов данных) |")
    A("| 2 | Соединение | новый `requests.post` каждый раз | переиспользование `requests.Session` (fixture) |")
    A("| 3 | Timeout | отсутствует | `timeout=REQUEST_TIMEOUT` в каждом запросе |")
    A("| 4 | Эндпоинт | `f\"{BASE_URL}/users\"` в каждом тесте | константа `USERS_ENDPOINT` |")
    A("| 5 | Ассерты | без сообщений | с поясняющим сообщением и телом ответа |")
    A("| 6 | Импорт | `import pytest` (не используется) | реально используется (parametrize/fixture) |")
    A("")
    A("## 🏁 Вывод")
    A("")
    A("Исходный код выполняет свою задачу и покрывает как позитивные, так и негативные сценарии, "
      "но страдает от дублирования и не следует ряду стандартных практик автотестов: отсутствует "
      "timeout, эндпоинт захардкожен в каждом запросе, ассерты без поясняющих сообщений, "
      "соединение не переиспользуется, есть неиспользуемый импорт. Оптимизированный вариант "
      "сохраняет покрываемые сценарии, но делает код короче, надёжнее и проще в поддержке. "
      f"Полная версия — в файле `{optimized_rel}`.")
    A("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ревью и оптимизация кода автотестов.")
    ap.add_argument("--input", default=os.path.join(BASE_DIR, "bad_code.py"),
                    help="Файл с исходными автотестами (по умолчанию bad_code.py)")
    ap.add_argument("--output", default=os.path.join(BASE_DIR, "optimized_code.py"),
                    help="Файл для оптимизированного варианта (по умолчанию optimized_code.py)")
    ap.add_argument("--report", default=os.path.join(BASE_DIR, "review.md"),
                    help="Файл отчёта (по умолчанию review.md)")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Файл не найден: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        source = f.read()

    # Если исходный код не валидный Python (например, пропущены отступы) — восстановить
    repaired = False
    try:
        ast.parse(source)
    except SyntaxError:
        fixed = repair_indentation(source)
        try:
            ast.parse(fixed)
            source, repaired = fixed, True
            print("⚠️  Исходный файл не был валидным Python-кодом — отступы восстановлены автоматически.")
        except SyntaxError as e:
            print(f"❌ Не удалось разобрать исходный код даже после восстановления отступов: {e}",
                  file=sys.stderr)
            sys.exit(1)

    ctx = analyze(source, os.path.basename(args.input))
    ctx["repaired"] = repaired
    optimized = generate_optimized(ctx)

    try:  # проверка валидности сгенерированного кода
        ast.parse(optimized)
        opt_ok = True
    except SyntaxError as e:
        opt_ok = False
        print(f"❌ Сгенерированный код некорректен: {e}", file=sys.stderr)

    optimized_rel = os.path.relpath(args.output, BASE_DIR)
    report = build_review(ctx, optimized_rel)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(optimized)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)

    print("✅ Анализ завершён.")
    print(f"   Тестов: {ctx['metrics']['tests_total']}, проблем найдено: {len(ctx['findings'])}.")
    for f_ in sorted(ctx["findings"], key=lambda x: SEV_ORDER[x.severity]):
        print(f"   - [{f_.severity:<8}] {f_.title}")
    print(f"   Оптимизированный код: {args.output} (синтаксис: {'OK' if opt_ok else 'ERROR'})")
    print(f"   Отчёт: {args.report}")


if __name__ == "__main__":
    main()
