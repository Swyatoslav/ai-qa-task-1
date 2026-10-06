#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для генерации тест-кейсов через Ollama и оценки ответов LLM.

Критерии оценки:
  - Полнота: покрытие граничных значений и сценариев
  - Формат: структурная целостность ответа
  - Точность: верность ожидаемых результатов (проверка через исполнение)

Результаты записываются в compare_answers_resuls.txt
"""

import re
import sys
import time
import requests
from datetime import datetime
from typing import List, Dict, Tuple, Any

from prompts import ALL_PROMPTS, FUNCTION_CODE

# ─── Конфигурация ────────────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"
MODEL = "llama3.2"          # модель Ollama (изменить при необходимости)
TIMEOUT = 120               # таймаут запроса в секундах
RESULT_FILE = "compare_answers_resuls.txt"
MAX_RETRIES = 2


# ─── Функция для верификации ─────────────────────────────────────────────────
def calculate_discount(price, discount_percent):
    if price < 0:
        raise ValueError("Цена не может быть отрицательной")
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Процент скидки должен быть от 0 до 100")
    return price * (1 - discount_percent / 100)


# ─── Вызов Ollama ────────────────────────────────────────────────────────────
def call_ollama(prompt: str, model: str = MODEL) -> str:
    """Вызывает Ollama API /api/generate (non-stream)."""
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 2048},
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES:
                print(f"  ⚠ Нет соединения с Ollama, повтор через 3с...")
                time.sleep(3)
            else:
                raise
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(2)
            else:
                raise


# ─── Извлечение тест-кейсов из ответа ────────────────────────────────────────
def extract_test_cases(response_text: str) -> List[Dict[str, Any]]:
    """Извлекает пары (price, discount) из ответа LLM."""
    cases = []

    # Пытаемся извлечь из таблицы
    table_cases = _extract_from_table(response_text)
    if table_cases:
        return table_cases

    # По строкам
    price_re = r'price\s*[:=]\s*(-?\d+\.?\d*)'
    lines = response_text.split('\n')
    current_block = []

    for line in lines:
        if re.search(price_re, line, re.IGNORECASE):
            if current_block:
                _parse_block(current_block, cases)
            current_block = [line]
        elif current_block:
            current_block.append(line)

    if current_block:
        _parse_block(current_block, cases)

    if not cases:
        _parse_whole_text(response_text, cases)

    return cases


def _extract_from_table(text: str) -> List[Dict]:
    """Извлекает тест-кейсы из markdown-таблицы."""
    cases = []
    price_re = r'price\s*[:=]\s*(-?\d+\.?\d*)'

    for line in text.split('\n'):
        if not re.search(price_re, line, re.IGNORECASE):
            continue
        # Разбиваем строку таблицы на ячейки
        cells = [c.strip() for c in line.split('|')]
        pm = re.search(price_re, line, re.IGNORECASE)
        dm = re.search(r'(?:discount_percent|discount)\s*[:=]\s*(-?\d+\.?\d*)', line, re.IGNORECASE)
        if pm and dm:
            price = float(pm.group(1))
            discount = float(dm.group(1))
            # Ищем ожидаемый результат в соседних ячейках
            expected = ""
            for cell in cells:
                if cell and cell != line:
                    cell_clean = cell.strip()
                    # Если ячейка содержит число или текст ошибки
                    if re.match(r'^-?\d+\.?\d*$', cell_clean):
                        expected = cell_clean
                        break
                    if 'error' in cell_clean.lower() or 'ошибк' in cell_clean.lower() or \
                       'цена' in cell_clean.lower() or 'процент' in cell_clean.lower():
                        expected = cell_clean
                        break
            if not expected:
                expected = _find_expected_in_text(line)
            cases.append({"price": price, "discount": discount, "expected": expected})

    return cases


def _parse_block(lines: List[str], cases: List[Dict]) -> None:
    text = '\n'.join(lines)
    pm = re.search(r'price\s*[:=]\s*(-?\d+\.?\d*)', text, re.IGNORECASE)
    dm = re.search(r'(?:discount_percent|discount)\s*[:=]\s*(-?\d+\.?\d*)', text, re.IGNORECASE)
    if pm and dm:
        price = float(pm.group(1))
        discount = float(dm.group(1))
        expected = _find_expected_in_text(text)
        cases.append({"price": price, "discount": discount, "expected": expected})


def _parse_whole_text(text: str, cases: List[Dict]) -> None:
    pattern = r'price\s*[:=]\s*(-?\d+\.?\d*)\D*(?:discount_percent|discount)\s*[:=]\s*(-?\d+\.?\d*)'
    for m in re.finditer(pattern, text, re.IGNORECASE):
        price = float(m.group(1))
        discount = float(m.group(2))
        expected = _find_expected_near(text, m.end())
        cases.append({"price": price, "discount": discount, "expected": expected})


def _find_expected_in_text(text: str) -> str:
    patterns = [
        r'(?:ожидан[ае]|expected|результат)\s*[:\-]?\s*(.*)',
        r'(?:ValueError|ошибка|exception)\s*[:\-]?\s*(.*)',
        r'return\s+([0-9.]+)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:100]
    return ""


def _find_expected_near(text: str, pos: int) -> str:
    context = text[pos:pos + 200]
    m = re.search(r'(?:ожидан[ае]|expected|результат)\s*[:\-]?\s*(.*)', context, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:100]
    m = re.search(r'(ValueError|ошибка|exception)', context, re.IGNORECASE)
    if m:
        return "ValueError"
    return ""


# ─── Критерий 1: Полнота ─────────────────────────────────────────────────────
def evaluate_completeness(response_text: str) -> Tuple[int, List[str]]:
    """Оценивает полноту покрытия сценариев. Макс: 6"""
    score = 0
    details = []
    text = response_text.lower()

    if re.search(r'(100\s*,\s*\d+|price\s*=\s*\d+[,;])|(нормальн|обычный|корректн|valid|позитивн)', text):
        score += 1
        details.append("✅ Обычный случай")
    else:
        details.append("❌ Обычный случай")

    if re.search(r'(discount.*\s0[^0-9.])|(0\s*%)|(discount.*=.*\b0\b)', text):
        score += 1
        details.append("✅ Граница discount=0")
    else:
        details.append("❌ Граница discount=0")

    if re.search(r'(discount.*\s100\b)|(100\s*%)', text):
        score += 1
        details.append("✅ Граница discount=100")
    else:
        details.append("❌ Граница discount=100")

    if re.search(r'(-\d+.*price|price.*-\d+|отрицательн.*цен|negative.*price|price.*<\s*0)', text):
        score += 1
        details.append("✅ Отрицательная цена")
    else:
        details.append("❌ Отрицательная цена")

    if re.search(r'((?:1[0-9]{2,}|[2-9]\d{2})\s*%|discount.*>\s*100|превышает.*100|101|150|200)', text):
        score += 1
        details.append("✅ discount > 100")
    else:
        details.append("❌ discount > 100")

    if re.search(r'(-\d+\s*%|отрицательн.*скид|discount.*<\s*0|discount.*-)', text):
        score += 1
        details.append("✅ Отрицательный discount")
    else:
        details.append("❌ Отрицательный discount")

    return score, details


# ─── Критерий 2: Формат ──────────────────────────────────────────────────────
def evaluate_format(response_text: str) -> Tuple[int, List[str]]:
    """Оценивает форматирование ответа. Макс: 5"""
    score = 0
    details = []

    has_table = '|' in response_text and ('---' in response_text or response_text.count('|') > 10)
    numbered_items = len(re.findall(r'^\s*\d+[.)]\s', response_text, re.MULTILINE))
    bullet_items = len(re.findall(r'^\s*[-*+]\s', response_text, re.MULTILINE))

    if has_table:
        score += 1
        details.append("✅ Табличная структура")
    elif numbered_items >= 3:
        score += 1
        details.append(f"✅ Нумерованный список ({numbered_items} элементов)")
    elif bullet_items >= 3:
        score += 1
        details.append(f"✅ Маркированный список ({bullet_items} элементов)")
    else:
        details.append("❌ Структура не определена")

    if re.search(r'(TC\s*-?\s*\d+|ТК\s*-?\s*\d+|Test\s*Case\s*\d+|ID\s*[:#]\s*\d+|\d+\s*\.\s)', response_text):
        score += 1
        details.append("✅ Идентификаторы тест-кейсов")
    else:
        details.append("❌ Идентификаторы тест-кейсов")

    headers = re.findall(r'^#{1,3}\s+(.+)', response_text, re.MULTILINE)
    bold_sections = re.findall(r'^\*\*(.+)\*\*$', response_text, re.MULTILINE)
    if len(headers) >= 2 or len(bold_sections) >= 2:
        score += 1
        details.append("✅ Разделение на секции")
    else:
        details.append("❌ Разделение на секции")

    if re.search(r'(ожидан|expected|результат|result)', response_text, re.IGNORECASE):
        score += 1
        details.append("✅ Поле 'Ожидаемый результат'")
    else:
        details.append("❌ Поле 'Ожидаемый результат'")

    if re.search(r'(вход|input|данные|price|параметр)', response_text, re.IGNORECASE):
        score += 1
        details.append("✅ Поле 'Входные данные'")
    else:
        details.append("❌ Поле 'Входные данные'")

    return score, details


# ─── Критерий 3: Точность ────────────────────────────────────────────────────
def evaluate_accuracy(response_text: str) -> Tuple[int, List[str]]:
    """Проверяет точность: верифицирует ожидаемые результаты. Макс: 5"""
    score = 0
    details = []

    cases = extract_test_cases(response_text)
    total = len(cases)

    if total == 0:
        score, details = _accuracy_by_text(response_text)
        return score, details

    correct = 0
    incorrect = 0
    error_cases = 0

    for case in cases:
        price = case["price"]
        discount = case["discount"]
        expected_str = case["expected"].lower()

        # Определяем, ожидалась ли ошибка (по началу текста)
        expects_error = (
            expected_str.startswith("valueerror")
            or expected_str.startswith("ошибк")
            or expected_str.startswith("exception")
            or "valueerror" in expected_str[:30]
            or "цена не может" in expected_str
            or "процент скидки должен" in expected_str
        )

        try:
            actual = calculate_discount(price, discount)
            if expects_error:
                incorrect += 1
            else:
                if _numbers_match(str(actual), expected_str):
                    correct += 1
                else:
                    incorrect += 1
        except ValueError:
            if expects_error:
                correct += 1
                error_cases += 1
            else:
                if re.search(r'\d+\.?\d*', expected_str):
                    incorrect += 1
                else:
                    correct += 1
                    error_cases += 1

    max_score = 5
    accuracy_ratio = correct / total
    score = round(accuracy_ratio * max_score)
    if correct == total:
        score = max_score

    details.append(f"Извлечено тест-кейсов: {total}")
    details.append(f"Верных: {correct}, неверных: {incorrect}")
    details.append(f"Проверено исключений: {error_cases}")
    if incorrect > 0:
        details.append("⚠ Есть несовпадения ожидаемых результатов")
    else:
        details.append("✅ Все ожидаемые результаты верны")

    return score, details


def _numbers_match(actual_str: str, expected_str: str) -> bool:
    """Проверяет совпадение чисел с допустимой погрешностью."""
    actual_nums = re.findall(r'-?\d+\.?\d*', actual_str)
    expected_nums = re.findall(r'-?\d+\.?\d*', expected_str)
    if not actual_nums or not expected_nums:
        return False
    try:
        a = float(actual_nums[0])
        e = float(expected_nums[0])
        return abs(a - e) < 0.01 * max(1, abs(a))
    except (ValueError, IndexError):
        return False


def _accuracy_by_text(response_text: str) -> Tuple[int, List[str]]:
    """Оценка точности по тексту (когда не удалось извлечь кейсы)."""
    score = 0
    details = []
    text = response_text.lower()

    if "цена не может быть отрицательной" in text or "отрицательн" in text:
        score += 1
        details.append("✅ Корректное сообщение об ошибке (цена)")
    else:
        details.append("❌ Сообщение об ошибке (цена) не найдено")

    if "процент скидки должен быть от 0 до 100" in text or "процент" in text or "0.*100" in text:
        score += 1
        details.append("✅ Корректное сообщение об ошибке (процент)")
    else:
        details.append("❌ Сообщение об ошибке (процент) не найдено")

    if re.search(r'(1\s*-\s*discount|100\s*-\s*discount|discount.*100|\*\s*100)', text):
        score += 1
        details.append("✅ Формула расчёта")
    else:
        details.append("❌ Формула расчёта не описана")

    if re.search(r'(100.*10.*→.*90|90|result.*90|ожид.*90)', text):
        score += 1
        details.append("✅ Типовой расчёт (100, 10% → 90)")
    else:
        details.append("❌ Типовой расчёт не найден")

    if re.search(r'(price\s*=\s*0|0.*→.*0|результат.*0\b)', text):
        score += 1
        details.append("✅ Случай price=0")
    else:
        details.append("❌ Случай price=0 не найден")

    return score, details


# ─── Формирование отчёта ─────────────────────────────────────────────────────
def format_report(results: List[Dict], model: str = MODEL) -> str:
    """Формирует итоговый отчёт."""
    lines = []
    lines.append("=" * 70)
    lines.append("СРАВНЕНИЕ ОТВЕТОВ LLM — ТЕСТ-КЕЙСЫ ДЛЯ calculate_discount()")
    lines.append(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Модель: {model}")
    lines.append("=" * 70)
    lines.append("")

    # Сводная таблица
    lines.append("┌─────────────────────────────────────────────────────────────────────────────┐")
    lines.append("│ СВОДНАЯ ТАБЛИЦА                                                             │")
    lines.append("├──────────────────────────────┬──────────┬──────────┬──────────┬──────────────┤")
    lines.append("│ Промпт                       │ Полнота  │ Формат   │ Точность │ ИТОГО        │")
    lines.append("├──────────────────────────────┼──────────┼──────────┼──────────┼──────────────┤")

    for r in results:
        total = r["completeness"] + r["format"] + r["accuracy"]
        max_total = 16
        lines.append(
            f"│ {r['name']:<28} │ {r['completeness']:>4}/6  │ {r['format']:>4}/5  │ "
            f"{r['accuracy']:>4}/5  │ {total:>4}/{max_total}      │"
        )

    lines.append("└──────────────────────────────┴──────────┴──────────┴──────────┴──────────────┘")
    lines.append("")

    # Детали по каждому промпту
    for r in results:
        lines.append("-" * 70)
        lines.append(f"📝 {r['name']}")
        lines.append("-" * 70)
        lines.append("")

        lines.append(f"  Промпт (обрезан): {r['prompt'][:120]}...")
        lines.append("")
        lines.append(f"  Ответ LLM (первые 500 символов):")
        lines.append(f"  {'─' * 60}")
        for line in r["response"][:500].split('\n'):
            lines.append(f"  {line}")
        if len(r["response"]) > 500:
            lines.append(f"  ... (всего {len(r['response'])} символов)")
        lines.append(f"  {'─' * 60}")
        lines.append("")

        lines.append(f"  📊 Оценка:")
        lines.append(f"     Полнота:  {r['completeness']}/6")
        for d in r["completeness_details"]:
            lines.append(f"       {d}")
        lines.append(f"     Формат:   {r['format']}/5")
        for d in r["format_details"]:
            lines.append(f"       {d}")
        lines.append(f"     Точность: {r['accuracy']}/5")
        for d in r["accuracy_details"]:
            lines.append(f"       {d}")
        lines.append("")

    # Вывод
    lines.append("=" * 70)
    lines.append("ВЫВОД")
    lines.append("=" * 70)
    lines.append(_make_conclusion(results))
    lines.append("")
    lines.append("=" * 70)
    lines.append("КОНЕЦ ОТЧЁТА")
    lines.append("=" * 70)

    return '\n'.join(lines)


def _make_conclusion(results: List[Dict]) -> str:
    """Формирует заключение."""
    lines = []
    best = max(results, key=lambda r: r["completeness"] + r["format"] + r["accuracy"])
    lines.append(f"Лучший промпт по суммарной оценке: {best['name']}")
    lines.append(f"  (Полнота: {best['completeness']}/6, Формат: {best['format']}/5, "
                 f"Точность: {best['accuracy']}/5)")
    lines.append("")
    lines.append("Сравнение подходов:")
    for r in results:
        total = r["completeness"] + r["format"] + r["accuracy"]
        lines.append(f"  • {r['name']}: {total}/16")
    lines.append("")
    lines.append("Рекомендации:")
    if any(r["completeness"] < 3 for r in results):
        lines.append("  • Минимальный промпт (без указаний) может давать неполное покрытие.")
    if any(r["format"] < 3 for r in results):
        lines.append("  • Указание формата в промпте повышает структурированность ответа.")
    if any(r["accuracy"] < 3 for r in results):
        lines.append("  • Рекомендуется явно указывать формулу расчёта для повышения точности.")
    return '\n'.join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Генерация тест-кейсов через Ollama и оценка LLM")
    print("=" * 60)
    print(f"Ollama: {OLLAMA_HOST}")
    print(f"Модель: {MODEL}")
    print(f"Промптов: {len(ALL_PROMPTS)}")
    print()

    # Проверяем доступность Ollama
    model_to_use = MODEL
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        print(f"✅ Ollama доступна. Модели: {', '.join(models)}")
        if MODEL not in [m.split(':')[0] for m in models]:
            print(f"⚠ Модель '{MODEL}' не найдена.")
            if models:
                print(f"  Используем: {models[0]}")
                model_to_use = models[0]
    except Exception as e:
        print(f"❌ Ollama недоступна: {e}")
        print("   Убедитесь, что Ollama запущена: `ollama serve`")
        print("   И модель скачана: `ollama pull llama3.2`")
        sys.exit(1)

    results = []

    for i, prompt_info in enumerate(ALL_PROMPTS, 1):
        name = prompt_info["name"]
        prompt = prompt_info["text"]
        print(f"\n[{i}/{len(ALL_PROMPTS)}] {name}")
        print(f"  Промпт: {prompt[:80]}...")
        print("  Генерация...", end=" ", flush=True)

        try:
            response = call_ollama(prompt, model_to_use)
            print(f"✅ ({len(response)} символов)")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            response = f"ERROR: {e}"

        # Оценка
        print("  Оценка...", end=" ", flush=True)

        completeness, completeness_details = evaluate_completeness(response)
        format_score, format_details = evaluate_format(response)
        accuracy, accuracy_details = evaluate_accuracy(response)

        print(f"✅ (П={completeness}/6, Ф={format_score}/5, Т={accuracy}/5)")

        results.append({
            "name": name,
            "prompt": prompt,
            "response": response,
            "completeness": completeness,
            "completeness_details": completeness_details,
            "format": format_score,
            "format_details": format_details,
            "accuracy": accuracy,
            "accuracy_details": accuracy_details,
        })

    # Формирование отчёта
    report = format_report(results, model_to_use)

    # Запись в файл
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n{'=' * 60}")
    print(f"✅ Отчёт сохранён: {RESULT_FILE}")
    print(f"{'=' * 60}")
    print(report)


if __name__ == "__main__":
    main()


