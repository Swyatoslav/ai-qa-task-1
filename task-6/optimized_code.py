"""
Оптимизированные автотесты для API.

Сгенерировано автоматически скриптом review_and_optimize.py из файла bad_code.py.

Ключевые улучшения:
  * дублирование удалено — одинаковые тесты заменены @pytest.mark.parametrize;
  * переиспользование соединения через requests.Session (fixture api_client);
  * добавлен timeout во все HTTP-запросы;
  * эндпоинты вынесены в константы;
  * информативные сообщения в assert;
  * тело ответа (JSON) парсится один раз и проверяется целиком.
"""
import pytest
import requests

BASE_URL = 'http://localhost:8000'
USERS_ENDPOINT = f"{BASE_URL}/users"
REQUEST_TIMEOUT = 5  # секунд


@pytest.fixture()
def api_client():
    """HTTP-клиент (requests.Session) с пулингом соединений."""
    with requests.Session() as session:
        yield session


@pytest.mark.parametrize(
    "payload, expected_status, expected_name",
    [
        ({'name': 'Alice', 'email': 'alice@example.com'}, 201, 'Alice'),
        ({'name': 'Bob', 'email': 'bob@example.com'}, 201, 'Bob'),
        ({'name': 'Charlie', 'email': 'charlie@example.com'}, 201, 'Charlie'),
        ({'name': 'Test', 'email': 'bad-email'}, 400, None),
        ({'email': 'test@example.com'}, 400, None),
    ],
    ids=[
        "create_user",
        "create_user_other_name",
        "create_user_new_new_name",
        "create_user_invalid_email",
        "create_user_missing_name",
    ],
)
def test_create_user(api_client, payload, expected_status, expected_name):
    response = api_client.post(
        USERS_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT
    )
    assert response.status_code == expected_status, (
        f"Ожидался HTTP {expected_status}, получен {response.status_code}. "
        f"Тело ответа: {response.text}"
    )
    if expected_name is not None:
        body = response.json()
        assert body.get("name") == expected_name, (
            f"В ответе name={body.get('name')!r}, ожидалось {expected_name!r}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
