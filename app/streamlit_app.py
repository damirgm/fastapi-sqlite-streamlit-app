"""
Streamlit frontend UI for admissions monitoring demo.
- Talks to FastAPI via HTTP requests (requests library).
- Filters: period, program, source, wave
- Shows KPI cards: applications, enrolled, conversion
- Shows simple charts (pandas + streamlit built-ins)
- CRUD: create application, update status, delete application
- CSV export uses backend /report.csv endpoint
"""

from __future__ import annotations

from datetime import date
import time
import pandas as pd
import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000"


def api_get(path: str, params: dict | None = None):
    r = requests.get(f"{API_URL}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r


def api_post(path: str, json: dict):
    r = requests.post(f"{API_URL}{path}", json=json, timeout=10)
    r.raise_for_status()
    return r.json()


def api_patch(path: str, json: dict):
    r = requests.patch(f"{API_URL}{path}", json=json, timeout=10)
    r.raise_for_status()
    return r.json()


def api_delete(path: str):
    r = requests.delete(f"{API_URL}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


st.set_page_config(page_title="Приёмная кампания — Дашборд (Demo)", layout="wide")

st.title("Дашборд мониторинга приёмной кампании (Demo)")

with st.sidebar:
    st.header("Фильтры")

    c1, c2 = st.columns(2)
    with c1:
        date_from = st.date_input("Период: от", value=date.today().replace(day=1))
    with c2:
        date_to = st.date_input("Период: до", value=date.today())

    programs = api_get("/programs").json()
    program_codes = ["(all)"] + [p["program_code"] for p in programs]
    program = st.selectbox("Направление (program_code)", program_codes)

    sources = ["(all)", "site", "olymp", "aggregator", "other"]
    source = st.selectbox("Источник (source)", sources)

    wave = st.selectbox("Волна (wave)", ["(all)", 1, 2, 3])

    st.caption("Фильтры применяются к списку заявок и метрикам.")

params = {
    "from": date_from.isoformat() if date_from else None,
    "to": date_to.isoformat() if date_to else None,
    "program": None if program == "(all)" else program,
    "source": None if source == "(all)" else source,
    "wave": None if wave == "(all)" else wave,
}

# Performance target: try to keep UI response <=2 sec on test dataset T1
t0 = time.time()
metrics = api_get("/metrics", params=params).json()
apps = api_get("/applications", params={**params, "include_related": True}).json()
elapsed = time.time() - t0

st.caption(f"Отклик (тест): {elapsed:.3f} сек (цель ≤ 2 сек на T1)")

# KPI cards
col1, col2, col3 = st.columns(3)
col1.metric("Заявки (applications)", metrics["applications"])
col2.metric("Зачислены (enrolled)", metrics["enrolled"])
col3.metric("Конверсия (conversion)", f'{metrics["conversion"]:.2%}')

# Show applied filters explicitly
with st.expander("Применённые фильтры"):
    st.write({
        "from": params["from"],
        "to": params["to"],
        "program": params["program"],
        "source": params["source"],
        "wave": params["wave"],
    })

# Table + basic charts
df = pd.json_normalize(apps)
if df.empty:
    st.warning("Нет данных по выбранным фильтрам.")
else:
    # Basic columns for beginners
    show_cols = [
        "id", "created_at", "status_changed_at",
        "program_code", "wave", "source", "status",
        "applicant.fio", "applicant.region", "applicant.birth_year",
        "program.program_name", "program.faculty",
    ]
    for c in show_cols:
        if c not in df.columns:
            df[c] = None

    st.subheader("Список заявок")
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # Dynamics chart: applications per day
    st.subheader("Динамика заявок (по дате подачи)")
    df["created_date"] = pd.to_datetime(df["created_at"]).dt.date
    by_day = df.groupby("created_date")["id"].count().reset_index(name="applications")
    st.line_chart(by_day.set_index("created_date"))

    # Funnel: status counts
    st.subheader("Воронка статусов")
    funnel = df.groupby("status")["id"].count().reindex(["new", "review", "enrolled", "rejected"]).fillna(0)
    st.bar_chart(funnel)

# CSV export
st.subheader("Экспорт отчёта (CSV)")
csv_text = api_get("/report.csv", params={
    "from": params["from"],
    "to": params["to"],
    "program": params["program"],
    "source": params["source"],
}).text
st.download_button(
    label="Скачать report.csv",
    data=csv_text.encode("utf-8"),
    file_name="report.csv",
    mime="text/csv",
)

# --- CRUD section ---
st.divider()
st.header("CRUD (демо-администрирование)")

tab1, tab2, tab3 = st.tabs(["Создать заявку", "Изменить статус / поля", "Удалить заявку"])

with tab1:
    st.subheader("Создать новую заявку")

    applicants = api_get("/applicants").json()
    applicant_options = {f'{a["id"]}: {a["fio"]}': a["id"] for a in applicants}
    programs = api_get("/programs").json()
    program_options = {f'{p["program_code"]}: {p["program_name"]}': p["program_code"] for p in programs}

    left, right = st.columns(2)
    with left:
        applicant_choice = st.selectbox("Абитуриент", list(applicant_options.keys()))
        program_choice = st.selectbox("Программа", list(program_options.keys()))
        wave_new = st.number_input("Волна", min_value=1, max_value=10, value=1, step=1)
    with right:
        source_new = st.selectbox("Источник", ["site", "olymp", "aggregator", "other"])
        status_new = st.selectbox("Статус", ["new", "review", "enrolled", "rejected"])

    if st.button("Создать заявку", type="primary"):
        try:
            payload = {
                "applicant_id": applicant_options[applicant_choice],
                "program_code": program_options[program_choice],
                "wave": int(wave_new),
                "source": source_new,
                "status": status_new,
            }
            created = api_post("/applications", payload)
            st.success(f"Создано: application_id={created['id']}")
            st.rerun()
        except requests.HTTPError as e:
            st.error(f"Ошибка API: {e.response.status_code} {e.response.text}")

with tab2:
    st.subheader("Обновить заявку (PATCH)")
    app_id = st.number_input("ID заявки", min_value=1, value=1, step=1)

    colA, colB, colC = st.columns(3)
    with colA:
        new_status = st.selectbox("Новый статус", ["(no change)", "new", "review", "enrolled", "rejected"])
    with colB:
        new_source = st.selectbox("Новый источник", ["(no change)", "site", "olymp", "aggregator", "other"])
    with colC:
        new_wave = st.selectbox("Новая волна", ["(no change)", 1, 2, 3])

    username = st.text_input("Кто меняет (username для лога)", value="ui_user")

    if st.button("Обновить", type="primary"):
        try:
            payload = {"username": username}
            if new_status != "(no change)":
                payload["status"] = new_status
            if new_source != "(no change)":
                payload["source"] = new_source
            if new_wave != "(no change)":
                payload["wave"] = int(new_wave)

            updated = api_patch(f"/applications/{int(app_id)}", payload)
            st.success(f"Обновлено: application_id={updated['id']}")
            logs = api_get("/status_logs", params={"application_id": int(app_id)}).json()
            if logs:
                st.write("Логи смен статуса:")
                st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
            st.rerun()
        except requests.HTTPError as e:
            st.error(f"Ошибка API: {e.response.status_code} {e.response.text}")

with tab3:
    st.subheader("Удалить заявку")
    del_id = st.number_input("ID для удаления", min_value=1, value=1, step=1)
    confirm = st.checkbox("Да, я хочу удалить эту заявку")

    if st.button("Удалить", disabled=not confirm):
        try:
            api_delete(f"/applications/{int(del_id)}")
            st.success("Удалено")
            st.rerun()
        except requests.HTTPError as e:
            st.error(f"Ошибка API: {e.response.status_code} {e.response.text}")


st.caption("Подсказка: если API недоступен, запусти backend командой `uvicorn app.main:app --reload`.")
