import argparse
import json
import textwrap
from typing import List

try:
    from ollama import Client
except ImportError:
    print("Ошибка: Библиотека 'ollama' не найдена. Установите её командой:")
    print("pip install ollama")
    exit(1)


def generate_scenarios(count: int) -> str:
    """
    Формирует промпт и отправляет запрос к Ollama для генерации сценариев тестирования.
    Использует модель llama3.1:8b-instruct-fp16.
    """

    print("🤖 Проверочный запрос")
    try:
        client = Client(host='http://localhost:11434')
        # Легкий проверочный запрос, чтобы убедиться, что сервер отвечает
        client.generate(model='llama3.1:8b-instruct-fp16', prompt='Эхо-тест.')
    except Exception as e:
        return f"❌ Не удалось подключиться к Ollama по адресу http://localhost:11434.\nДетали ошибки: {e}\n\nУбедитесь, что:\n1. Ollama запущен (`open -a Ollama` или через терминал).\n2. Модель загружена (`ollama pull llama3.1:8b-instruct-fp16`)."

    print("🤖 Проверка прошла!")
    system_prompt = """Ты — ведущий инженер по тестированию ПО. 
Твоя задача: составить подробные, но лаконичные чек-листы в формате Markdown для ручного тестирования.
Используй только предоставленное описание интерфейса. Не придумывай несуществующие поля (например, email), если они не указаны во входных данных."""

    user_prompt = f"""
Сгенерируй ровно {count} уникальных сценариев тестирования для веб-формы регистрации пользователя.

Описание полей формы:
* Поле "Имя пользователя": текстовое поле.
* Поле "Пароль": поле ввода пароля (type="password").
* Поле "Подтверждение пароля": поле ввода пароля (type="password").
* Кнопка "Зарегистрировать".

Требования к форматам ответов:
1. Сценарии должны быть разделены горизонтальными линиями (`---`).
2. Каждый сценарий должен содержать:
   - **ID**: Уникальный номер (начиная с 1).
   - **Название**: Краткое название теста.
   - **Тип**: Позитивный / Негативный.
   - **Предусловия**: Что должно быть выполнено до начала теста.
   - **Шаги**: Пронумерованный список действий.
   - **Ожидаемый результат**.
3. Обязательно включи проверку безопасности (маскировка символов в полях Пароль/Подтверждение).
4. Если количество > 1, обязательно должны присутствовать как позитивные, так и негативные тесты. Распредели их примерно поровну. Если сценарий один - это позитивный сценарий.
5. Негативные сценарии должны покрывать разные классы ошибок: валидация формата имени, несоответствие паролей, пустые поля, слишком короткие значения.

Начни ответ сразу со списка сценариев без вводного текста.
ВАЖНО!!! Ответ должен быть исключительно в синтаксисе markdown (.md)
"""

    print("🤖 Отправляем промпт!")
    try:
        response = client.chat(
            model='llama3.1:8b-instruct-fp16',
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        generated_text = response['message']['content']

        # Очистка от возможных markdown fence, которые иногда добавляет LLM
        if generated_text.startswith('```'):
            lines = generated_text.split('\n')
            if lines[0].startswith('```') and lines[-1].startswith('```'):
                generated_text = '\n'.join(lines[1:-1])
        print("🤖 Сформировали ответ!")

        return generated_text.strip()

    except Exception as e:
        return f"❌ Ошибка при взаимодействии с моделью Ollama: {e}"


def main():
    parser = argparse.ArgumentParser(description="Генератор тестовых сценариев для формы регистрации на базе Ollama.")
    parser.add_argument(
        "-c", "--count",
        type=int,
        default=5,
        help="Количество генерируемых сценариев (по умолчанию: 5)"
    )
    args = parser.parse_args()

    count = max(1, min(args.count, 20))  # Ограничиваем разумным диапазоном от 1 до 20

    print(f"🤖 Отправка запроса в Ollama ({count} сценариев)...\n")

    result = generate_scenarios(count)

    # Если вернулась ошибка подключения, выводим её и завершаем работу
    if result.startswith("❌"):
        print(result)
        return

    print("# Тестовые сценарии для формы регистрации\n")
    print(result)
    print("\n---")
    print(f"Сгенерировано сценариев: {count}")


if __name__ == "__main__":
    main()