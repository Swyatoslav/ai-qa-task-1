#!/usr/bin/env python3
"""
Бот для ответов на вопросы по управлению web-сервером.

Принимает путь к JSON-файлу с инструкциями (вопрос → ответ) и
ведёт диалог с пользователем, отвечая на вопросы согласно документации.

Формат JSON-файла:
{
  "вопрос пользователя": "ответ бота",
  ...
}

Запуск:
  python3 web_server_bot.py --doc doc.json
"""

import argparse
import json
import re
import sys


def load_documentation(path: str) -> dict:
    """Загружает документацию из JSON-файла."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Ошибка: файл '{path}' не найден.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Ошибка: файл '{path}' содержит некорректный JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"Ошибка: JSON должен быть объектом (словарём) вида {{\"вопрос\": \"ответ\"}}.", file=sys.stderr)
        sys.exit(1)

    return data


def normalize(text: str) -> str:
    """Нормализует текст для сравнения."""
    text = text.lower().strip()
    text = re.sub(r'[.?!,;:]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def find_answer(user_input: str, doc: dict) -> str:
    """Ищет ответ в документации по вопросу пользователя."""
    q = normalize(user_input)

    # 1. Точное совпадение
    for question, answer in doc.items():
        if normalize(question) == q:
            return answer

    # 2. Подстрока: вопрос пользователя содержит ключ документации
    for question, answer in doc.items():
        nq = normalize(question)
        if nq in q or q in nq:
            return answer

    # 3. Частичное совпадение по словам
    best_score = 0
    best_answer = None
    q_words = set(q.split())
    for question, answer in doc.items():
        nq_words = set(normalize(question).split())
        common = q_words & nq_words
        score = len(common)
        if score > best_score:
            best_score = score
            best_answer = answer

    if best_answer and best_score >= 2:
        return best_answer

    # 4. Не найден
    available_questions = '\n'.join(f"  • {q}" for q in doc.keys())
    return (
        "Я не уверен, что понял ваш вопрос.\n\n"
        f"Я умею отвечать на следующие вопросы:\n{available_questions}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Бот поддержки web-сервера. Отвечает на вопросы согласно JSON-документации."
    )
    parser.add_argument(
        '--doc',
        required=True,
        help="Путь к JSON-файлу с документацией (вопрос → ответ)"
    )
    args = parser.parse_args()

    doc = load_documentation(args.doc)
    print(f"Загружено вопросов: {len(doc)} (файл: {args.doc})")
    print("Задайте вопрос (или 'exit' для выхода):\n")

    while True:
        try:
            user_input = input("Вы: ")
        except (EOFError, KeyboardInterrupt):
            print("\nПока!")
            break

        if not user_input.strip():
            continue
        if user_input.strip().lower() in ('exit', 'quit', 'выход'):
            print("Пока!")
            break

        answer = find_answer(user_input, doc)
        print(f"Бот: {answer}\n")


if __name__ == "__main__":
    main()