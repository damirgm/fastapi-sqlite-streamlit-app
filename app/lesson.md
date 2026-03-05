# Урок (1 час): Быстрый прототип «Приёмная кампания ВУЗа» на FastAPI + Streamlit + SQLite

Цель занятия: собрать рабочий демо-прототип с CRUD и дашбордом за 60 минут.

---

## 0–5 мин — Введение

### Что такое FastAPI
- FastAPI — это Python-фреймворк для создания API.
- Плюсы: скорость разработки, автодокументация Swagger, валидация входных данных.

### Что такое Streamlit
- Streamlit — инструмент для создания UI (дашбордов) буквально за минуты.
- Плюсы: не нужно писать HTML/JS, всё на Python.

### Что такое SQLite
- SQLite — файловая база данных. Удобно для учебных проектов: просто файл `database.db`.

**Вопросы студентам:**
1. Чем API отличается от UI?
2. Почему SQLite удобен для обучения?

---

## 5–15 мин — Установка и структура проекта

### 1) Создаём папку проекта и виртуальное окружение

```bash
mkdir fastapi-sqlite-streamlit-app
cd fastapi-sqlite-streamlit-app

python -m venv .venv
# Windows:
# .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

### 2) Структура

Создай папку `app/` и положи туда файлы:

- `app/main.py` — backend (FastAPI)
- `app/streamlit_app.py` — frontend (Streamlit)
- `app/requirements.txt` — зависимости
- `app/database.db` — создастся автоматически (не создаём руками)

### 3) Установка зависимостей

```bash
pip install -r app/requirements.txt
```

**Где “скриншот”:**
- Скрин 1: структура папок в проводнике/VS Code.

**Мини-домашка (на завтра):**
- Добавить поле `email` в абитуриента (Applicant) и вывести его в UI.

---

## 15–30 мин — Backend (FastAPI): разбор main.py

### Шаг 1. Модели SQLModel
В `main.py` есть таблицы:
- `applicants` (абитуриенты)
- `programs` (направления)
- `applications` (заявки)
- `status_logs` (лог смен статусов)

Почему SQLModel:
- Это “2 в 1”: ORM (SQLAlchemy) + схемы (Pydantic-подобная валидация).

### Шаг 2. Engine и сессия
```python
engine = create_engine("sqlite:///./database.db")
```
Сессия через `Depends(get_session)`:
- Каждому запросу — отдельная DB-сессия
- Удобно и безопасно для новичков

### Шаг 3. CRUD эндпоинты
Проверяем, что есть:
- POST/GET/DELETE для Applicants и Programs
- POST/GET/PATCH/DELETE для Applications

### Шаг 4. Валидации (минимум 5)
В проекте сделано:
1. `program_code` не пуст
2. `status` строго из `new/review/enrolled/rejected` (Enum)
3. `created_at <= status_changed_at`
4. FK applicant_id существует
5. FK program_code существует
6. `source` из белого списка (site/olymp/aggregator/other)

### Шаг 5. “Политика при зачислении”
Если заявка стала `enrolled`, остальные активные заявки абитуриента (`new/review`) автоматически переводятся в `rejected`.
Это демонстрация бизнес-правила.

**Где “скриншот”:**
- Скрин 2: Swagger UI на `/docs`.

**Вопросы студентам:**
1. Почему лучше валидировать данные на backend, даже если есть UI?
2. Чем PATCH отличается от PUT?

---

## 30–45 мин — Frontend (Streamlit): streamlit_app.py

### Что делает UI
- Слева фильтры: период, program_code, source, wave
- KPI: applications, enrolled, conversion
- Таблица заявок
- Графики: динамика заявок, воронка статусов
- CRUD: создать/обновить/удалить
- Экспорт CSV

### Почему requests
- Streamlit общается с backend через HTTP как “обычный клиент”.

**Где “скриншот”:**
- Скрин 3: UI Streamlit в браузере (таблица + KPI).

**Вопросы студентам:**
1. Почему мы не подключаемся к SQLite напрямую из Streamlit?
2. Что проще тестировать: UI или API?

---

## 45–55 мин — Тестирование (ручное)

### 1) Запуск backend
Из корня проекта:

```bash
uvicorn app.main:app --reload
```

Открыть:
- Swagger UI: `http://127.0.0.1:8000/docs`

Проверки:
- GET `/programs` — есть направления
- GET `/applications` — есть ≥100 заявок (синтетика)

### 2) Запуск frontend
В новом терминале:

```bash
streamlit run app/streamlit_app.py
```

Открыть ссылку, которую покажет Streamlit.

### 3) Проверка CRUD сценария
- Создай заявку
- Переведи статус в enrolled
- Посмотри, что остальные заявки этого абитуриента стали rejected (политика)
- Удали заявку

---

## 55–60 мин — Расширение: что дальше

Идеи:
- Docker (2 контейнера: API + UI)
- PostgreSQL вместо SQLite
- Авторизация и роли (приёмная комиссия / факультеты / аналитики)
- Отчёты по бакетам (день/неделя), отдельная таблица событий

---

## Домашка (обязательная)
1. Добавить поле **priority** (1–5) в `applications`.
2. Показать priority в таблице Streamlit.
3. Добавить фильтр “priority >= …”.
4. В README/lesson описать миграцию БД: почему в демо можно пересоздавать, а в проде нужны Alembic-миграции.

Удачи!
