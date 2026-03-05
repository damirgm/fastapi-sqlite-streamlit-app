Структура проекта

app/
  main.py
  streamlit_app.py
  requirements.txt
  lesson.md
  database.db          # создастся автоматически при первом запуске

Как запустить (демо-сценарий)

# 1) установить зависимости
pip install -r app/requirements.txt

# 2) запустить backend
uvicorn app.main:app --reload

# 3) в другом терминале запустить UI
streamlit run app/streamlit_app.py

Проверка:

API: http://127.0.0.1:8000/docs
Streamlit: откроется в браузере автоматически
CSV: кнопка “Скачать report.csv”
