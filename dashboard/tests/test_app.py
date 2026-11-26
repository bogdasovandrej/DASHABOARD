# Прогоняем сам интерфейс без браузера: страницы открываются, пробная анкета сохраняется и даёт ожидаемый результат.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402


def fill(at, scores, good="", bad=""):
    for qid in ["s_tasks", "s_load", "s_mentor", "s_growth", "s_team", "s_overall", "s_stay"]:
        at.radio(key=f"f_{qid}").set_value(scores)
    at.radio(key="f_s_nps").set_value(scores * 2)
    at.text_area(key="f_s_good").set_value(good)
    at.text_area(key="f_s_bad").set_value(bad)


def test_pages_and_form(tmp_path, monkeypatch):
    import streamlit as st
    st.cache_resource.clear()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app.db"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.button[0].click().run()  # "Загрузить демо-данные"
    assert not at.exception
    for page in ["Обзор", "Стажёр", "Эффект", "Данные", "Анкета"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page

    # лента действий: отмечаем первое действие сделанным, оно уходит из ленты
    at.sidebar.radio[0].set_value("Обзор").run()
    text = " ".join(m.value for m in at.markdown)
    assert "Что сделать" in text and "Цитата" in text
    assert len([b for b in at.button if b.key and b.key.startswith("done_")]) == 7
    at.button(key="done_Кузнецов Илья").click().run()
    assert not at.exception
    assert len([b for b in at.button if b.key and b.key.startswith("done_")]) == 6
    at.sidebar.radio[0].set_value("Анкета").run()

    # анкета "на отвали": все пятёрки, без текста, за пару секунд
    at.text_input(key="f_name").set_value("Ленивый Тест")
    fill(at, 5)
    at.button[0].click().run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "заполнена формально" in text and "все оценки одинаковые" in text

    # честная анкета с жалобой: сигнал из текста должен перевесить хорошие оценки
    at.text_input(key="f_name").set_value("Честный Тест")
    fill(at, 4, good="Хорошая команда, все помогают", bad="Получил оффер в другой компании, думаю уходить")
    at.button[0].click().run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "намерение уйти" in text
    assert any("Критичный сигнал" in m.value for m in at.markdown)


def test_data_page_preflights_and_imports_upload(tmp_path, monkeypatch):
    import streamlit as st

    st.cache_resource.clear()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "upload.db"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Данные").run()
    content = (
        "ФИО стажёра,Подразделение,Наставник,Месяц стажировки,"
        "Мне понятны мои задачи и что от меня ждут\n"
        "Тестов Тест,Аналитика,Белов А.,1,4\n"
        "Тестов Тест,Аналитика,Белов А.,7,4\n"
    ).encode("utf-8")
    at.file_uploader[0].set_value(("ответы.csv", content, "text/csv")).run()

    assert not at.exception
    assert any("Предварительная проверка без записи в базу" in item.value for item in at.caption)
    assert any("1 строк с месяцем вне 1–6" in item.value for item in at.info)
    next(button for button in at.button if button.label == "Загрузить").click().run()
    assert not at.exception
    assert any("Загружено анкет: 1, ответов: 1" in item.value for item in at.success)
    assert any("Строк в источнике: 2" in item.value for item in at.success)
    st.cache_resource.clear()


def test_invalid_xlsx_stays_in_preview(tmp_path, monkeypatch):
    import streamlit as st

    from core import db, metrics

    st.cache_resource.clear()
    path = tmp_path / "invalid-xlsx.db"
    monkeypatch.setenv("DB_PATH", str(path))
    at = AppTest.from_file(str(ROOT / "app.py")).run()
    at.sidebar.radio[0].set_value("Данные").run()
    at.file_uploader[0].set_value(("ответы.xlsx", b"not an Excel file", "application/octet-stream")).run()

    assert not at.exception
    assert any("Предварительная проверка не пройдена" in item.value for item in at.warning)
    assert next(button for button in at.button if button.label == "Загрузить").disabled
    assert metrics.load(db.connect(path)).empty
    st.cache_resource.clear()


def test_card_shows_missing_month_for_each_role(tmp_path, monkeypatch):
    import json

    import streamlit as st

    from core import db, ingest, metrics

    st.cache_resource.clear()
    path = tmp_path / "missing-month.db"
    monkeypatch.setenv("DB_PATH", str(path))
    conn = db.connect(path)
    row = {"ФИО стажёра": "Тестов Тест", "Подразделение": "Аналитика", "Наставник": "Белов А."}
    interns = ingest.pd.DataFrame([
        {**row, "Месяц стажировки": 1, "Нагрузка мне по силам": 3},
        {**row, "Месяц стажировки": 3, "Нагрузка мне по силам": 2},
    ])
    mentors = ingest.pd.DataFrame([
        {**row, "Месяц стажировки": 1, "Качество работы стажёра": 4},
        {**row, "Месяц стажировки": 3, "Качество работы стажёра": 5},
        {**row, "Месяц стажировки": 4, "Качество работы стажёра": 5},
    ])
    ingest.save(conn, ingest.to_rows(interns, "intern")[0] + ingest.to_rows(mentors, "mentor")[0])
    monthly = metrics.monthly(metrics.load(conn))
    assert monthly.set_index("month").loc[3, ["s_avg", "m_avg"]].tolist() == [2, 5]
    at = AppTest.from_file(str(ROOT / "app.py")).run()
    at.sidebar.radio[0].set_value("Стажёр").run()

    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Оценка стажёра"] == "Нет ответа"
    assert {m.label: m.value for m in at.metric}["Оценка наставника"] == "5.0 / 5"
    assert any("Стажёр — 2, 4" in c.value and "Наставник — 2" in c.value for c in at.caption)
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert spec["data"][0]["x"] == [1, 2, 3, 4]
    assert spec["data"][0]["y"] == [3, None, 2, None]
    assert spec["data"][1]["y"] == [4, None, 5, 5]
    assert not any("низкая оценка держится второй месяц подряд" in m.value for m in at.markdown)
    st.cache_resource.clear()
