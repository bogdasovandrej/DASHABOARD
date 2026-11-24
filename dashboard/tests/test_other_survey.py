# Чужая анкета: другие названия вопросов, шкала 1-10, обратные вопросы, Excel, дубли и ФИО в разном написании.
# Истории стажёров те же, поэтому дашборд должен найти тех же людей.
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import comments, db, ingest, metrics, playbook  # noqa: E402

V2 = ROOT / "data" / "demo_v2"
MUST_BE_RED = ["Кузнецов Илья", "Соколова Дарья", "Морозов Артём", "Волкова Анна", "Новикова Полина", "Егоров Максим"]


def test_scale_conversion():
    assert ingest.to_five(10, 1, 10, 0) == 5
    assert ingest.to_five(1, 1, 10, 0) == 1
    assert ingest.to_five(10, 1, 10, 1) == 1   # обратный вопрос: 10 из 10 это плохо
    assert ingest.to_five(2, 1, 5, 1) == 4
    assert ingest.to_five(3, 1, 5, 0) == 3
    assert ingest.to_five(99, 1, 10, 0) == 5   # мусор за пределами шкалы не ломает расчёт


def test_name_cleanup():
    assert ingest.clean_name("  кузнецов   илья ") == "Кузнецов Илья"
    assert ingest.clean_name("КУЗНЕЦОВ ИЛЬЯ") == "Кузнецов Илья"
    assert ingest.clean_name("Белов А.") == "Белов А."


def test_second_survey(tmp_path, monkeypatch):
    monkeypatch.setenv("QUESTIONS_CSV", "survey/questions_v2.csv")
    conn = db.connect(tmp_path / "v2.db")
    r1 = ingest.ingest(conn, V2 / "otvety_stazhery.xlsx", "intern")
    r2 = ingest.ingest(conn, V2 / "otvety_nastavniki.xlsx", "mentor")
    assert not r1["нераспознанные колонки"] and not r2["нераспознанные колонки"]
    comments.run(conn, use_llm=False)
    a = metrics.load(conn)
    assert a["intern"].nunique() == 24                                       # разное написание ФИО склеилось
    assert a[a["role"] == "intern"].groupby(["intern", "month"]).ngroups == 119  # дубли не задвоились
    assert a[a["kind"] == "scale"]["score"].between(1, 5).all()

    mon = metrics.monthly(a)
    risk = metrics.risk_table(mon, metrics.comments(conn, a), a)
    lv = dict(zip(risk["intern"], risk["level"]))
    for name in MUST_BE_RED:
        assert lv[name] == "высокий", (name, lv[name])
    assert lv["Лебедев Никита"] == "средний"
    normal = risk[~risk["intern"].isin(MUST_BE_RED + ["Лебедев Никита"])]
    assert (normal["level"] == "высокий").sum() == 0

    # обратный вопрос про нагрузку распознан: перегруженному стажёру предлагают разговор, а не "мало задач"
    codes = dict(zip(risk["intern"], risk["codes"]))
    assert "overload" in codes["Кузнецов Илья"]
    assert playbook.pick(codes["Морозов Артём"]) == "no_tasks"
    m = metrics.mentors(a, mon).set_index("наставник")
    assert m.loc["Белов А.", "хватает времени"] == 1


def test_app_with_second_survey(tmp_path, monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    st.cache_resource.clear()  # иначе приложение возьмёт соединение с базой из предыдущего теста
    monkeypatch.setenv("QUESTIONS_CSV", "survey/questions_v2.csv")
    monkeypatch.setenv("DEMO_DIR", "data/demo_v2")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "app2.db"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    at.button[0].click().run()
    for page in ["Обзор", "Стажёр", "Эффект", "Данные", "Анкета"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page
    # в пробной анкете шкала взята из файла сопоставления
    assert at.radio(key="f_q1").options == [str(i) for i in range(1, 11)]


def test_old_answers_do_not_break_app(tmp_path, monkeypatch):
    # в базе остались ответы первой анкеты, а файл сопоставления уже от второй: дашборд должен сказать об этом, а не упасть
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from core.config import DEMO_DIR
    st.cache_resource.clear()
    monkeypatch.setenv("DB_PATH", str(tmp_path / "old.db"))
    conn = db.connect(tmp_path / "old.db")
    ingest.ingest(conn, DEMO_DIR / "otvety_stazhery.csv", "intern")
    monkeypatch.setenv("QUESTIONS_CSV", "survey/questions_v2.csv")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("другой анкеты" in w.value for w in at.warning)
    st.cache_resource.clear()


def test_excel_sheets_and_yes_no(tmp_path):
    import pandas as pd
    path = tmp_path / "two.xlsx"
    head = {"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 1}
    with pd.ExcelWriter(path) as w:
        pd.DataFrame([{**head, "Нагрузка мне по силам": "Нет", "Я узнаю новое и расту": "Да"}]).to_excel(w, "Стажёры", index=False)
        pd.DataFrame([{**head, "Качество работы стажёра": 4}]).to_excel(w, "Наставники", index=False)
    conn = db.connect(tmp_path / "s.db")
    ingest.ingest(conn, path, "intern", "Стажёры")
    ingest.ingest(conn, path, "mentor", "Наставники")
    a = metrics.load(conn).set_index("qid")["score"]
    assert a["s_load"] == 1 and a["s_growth"] == 5 and a["m_quality"] == 4


def test_import_rejects_file_without_recognized_answers(tmp_path):
    import pandas as pd
    import pytest

    conn = db.connect(tmp_path / "empty-import.db")
    source = pd.DataFrame([{
        "ФИО стажёра": "Тестов Тест",
        "Месяц стажировки": 1,
        "Время заполнения (сек)": 20,
        "Новый вопрос": "Ответ",
    }])

    with pytest.raises(ValueError, match="Не нашёл в файле колонок с ответами"):
        rows, _ = ingest.to_rows(source, "intern")
        ingest.save(conn, rows)
    assert metrics.load(conn).empty


def test_import_rejects_file_with_no_valid_answer_rows(tmp_path):
    import pandas as pd
    import pytest

    source = pd.DataFrame([{
        "ФИО стажёра": "Тестов Тест",
        "Месяц стажировки": "",
        "Нагрузка мне по силам": 4,
    }])
    with pytest.raises(ValueError, match="Не удалось извлечь ни одного ответа"):
        ingest.to_rows(source, "intern")


def test_file_import_requires_a_monthly_score_column():
    import pandas as pd
    import pytest

    source = pd.DataFrame([{
        "ФИО стажёра": "Тестов Тест",
        "Месяц стажировки": 1,
        "Что мешало или что хочется изменить?": "Сложно понять приоритеты",
    }])
    with pytest.raises(ValueError, match="динамика не рассчитается"):
        ingest.to_rows(source, "intern", require_average=True)


def test_question_map_rejects_duplicate_headers_and_invalid_ranges(tmp_path):
    import pandas as pd
    import pytest

    questions = pd.read_csv(ingest.questions_csv(), dtype=str).fillna("")
    questions.loc[questions["id"] == "s_tasks", "column"] = "Нагрузка мне по силам"
    path = tmp_path / "duplicate.csv"
    questions.to_csv(path, index=False)
    with pytest.raises(ValueError, match="сопоставлена нескольким вопросам"):
        ingest.load_questions(path)

    questions = pd.read_csv(ingest.questions_csv(), dtype=str).fillna("")
    questions.loc[questions["id"] == "s_tasks", ["min", "max"]] = ["5", "5"]
    path = tmp_path / "range.csv"
    questions.to_csv(path, index=False)
    with pytest.raises(ValueError, match="верхняя граница должна быть выше"):
        ingest.load_questions(path)

    questions = pd.read_csv(ingest.questions_csv(), dtype=str).fillna("")
    questions.loc[questions["kind"] == "nps", "max"] = "5"
    path = tmp_path / "nps-range.csv"
    questions.to_csv(path, index=False)
    with pytest.raises(ValueError, match="шкалу 0–10 или 1–10"):
        ingest.load_questions(path)

    questions = pd.read_csv(ingest.questions_csv(), dtype=str).fillna("")
    questions.loc[questions["id"] == "s_tasks", "max"] = "пять"
    path = tmp_path / "nonnumeric-range.csv"
    questions.to_csv(path, index=False)
    with pytest.raises(ValueError, match="нечисловые границы"):
        ingest.load_questions(path)


def test_import_reports_skipped_rows_and_invalid_answers():
    import pandas as pd

    source = pd.DataFrame([
        {"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 1, "Нагрузка мне по силам": 4},
        {"ФИО стажёра": "", "Месяц стажировки": 1, "Нагрузка мне по силам": 4},
        {"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 7, "Нагрузка мне по силам": 4},
        {"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 2, "Нагрузка мне по силам": "не знаю"},
        {"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 2, "Нагрузка мне по силам": 9},
    ])
    stats = {}
    rows, _ = ingest.to_rows(source, "intern", stats=stats)

    assert len(rows) == 1  # значение 9 вне шкалы 1–5 отброшено, а не превращено в оценку 5
    assert stats == {
        "строк без ФИО или месяца": 1,
        "ответов с неверным значением": 1,
        "ответов вне шкалы": 1,
        "строк с месяцем вне диапазона 1–6": 1,
    }


def test_six_month_panel_shape_for_five_pairs(tmp_path):
    import pandas as pd

    intern_rows, mentor_rows = [], []
    for pair in range(1, 6):
        for month in range(1, 7):
            meta = {
                "ФИО стажёра": f"Стажёр {pair}",
                "Подразделение": "Учебный пример",
                "Наставник": f"Наставник {pair}",
                "Месяц стажировки": month,
            }
            intern_rows.append({**meta, "Мне понятны мои задачи и что от меня ждут": 3 + month / 10})
            mentor_rows.append({**meta, "Качество работы стажёра": 4})

    conn = db.connect(tmp_path / "five-pairs-six-months.db")
    intern_answers, _ = ingest.to_rows(pd.DataFrame(intern_rows), "intern", require_average=True)
    mentor_answers, _ = ingest.to_rows(pd.DataFrame(mentor_rows), "mentor", require_average=True)
    ingest.save(conn, intern_answers + mentor_answers)
    monthly = metrics.monthly(metrics.load(conn))

    assert len(monthly) == 30
    assert sorted(monthly["month"].unique()) == [1, 2, 3, 4, 5, 6]
    assert monthly["s_avg"].notna().all() and monthly["m_avg"].notna().all()
    assert monthly["intern"].nunique() == 5


def test_enps_boundaries_and_missing_answers():
    import pandas as pd

    monthly = pd.DataFrame({"month": [1] * 5, "s_nps": [10, 9, 6, 6, 0]})
    assert metrics.enps(monthly, 1) == -20
    assert metrics.enps(pd.DataFrame({"month": [1], "s_nps": [None]}), 1) is None
