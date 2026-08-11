import requests
import pytest

BASE_URL = "https://jsonplaceholder.typicode.com"

@pytest.mark.parametrize("method, url, payload, headers, expected_status", [
    ("DELETE", "/posts/1", None, {}, 200),
    ("PATCH", "/posts/1", {"title": "foo"}, {'Content-type': 'application/json; charset=UTF-8'}, 200),
    ("PATCH", "/posts/some-string", {"title": 123}, {'Content-type': 'application/json; charset=UTF-8'}, 200)
])
def test_api_requests(method, url, payload, headers, expected_status):
    full_url = BASE_URL + url
    if method == "DELETE":
        response = requests.delete(full_url)
    elif method == "PATCH":
        response = requests.patch(full_url, json=payload, headers=headers)

    assert response.status_code == expected_status

# To run the tests use pytest command in terminal:
# pytest test_api.py -v