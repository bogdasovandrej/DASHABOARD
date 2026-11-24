# Прогоняем сам интерфейс без браузера: страницы открываются, пробная анкета сохраняется и даёт ожидаемый результат.
import os
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


def test_pages_and_form(tmp_path):
    import streamlit as st
    st.cache_resource.clear()
    os.environ["DB_PATH"] = str(tmp_path / "app.db")
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
    assert any("Поговорить на этой неделе" in m.value for m in at.markdown)


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
    ).encode("utf-8")
    at.file_uploader[0].set_value(("ответы.csv", content, "text/csv")).run()

    assert not at.exception
    assert any("Предварительная проверка без записи в базу" in item.value for item in at.caption)
    next(button for button in at.button if button.label == "Загрузить").click().run()
    assert not at.exception
    assert any("Загружено анкет: 1, ответов: 1" in item.value for item in at.success)
    st.cache_resource.clear()
