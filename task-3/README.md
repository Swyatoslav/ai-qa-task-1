# Тестирование API приложения https://jsonplaceholder.typicode.com

Автотесты на эндпоинты сервиса DELETE /posts/{id} и PATCH /posts/{id}

## Стек технологий

* docker
* ollama
* python
* requests
* pytest

## Инструкция по установке ollama в docker (для MacOS)

*   Устанавливаем docker командой
```
brew install --cask docker 
```

* Пуллим образ с ollama командой
```
docker pull ollama/ollama:latest
```
* Создаем контейнер образа через Docker Desktop (кликом по команде Run напротив образа в images)
* Открываем терминал образа через Docker Decktop
* В контейнере выполняем команду 
```
ollama pull rnj-1:8b
```
* В контейнере выполняем команду
```
ollama run rnj-1:8b
```
* В открывшуюся строку чата копируем содержимое файла /task-3/prompt.txt
* Дожидаемся результата

## Инструкция по запуску автотестов

* Устанавливаем python 3.13 с официального сайта
* Скачиваем IDE PyCharm CE
* В качестве интерпретатора ставим скачанный python согласно инструкциям в интернете (либо создаем venv, что предпочтительнее)
* Устанавливаем зависимости: pytest и requests
* Запускаем автотесты командой /venv/bin/python pytest /task-3/test_api.py
