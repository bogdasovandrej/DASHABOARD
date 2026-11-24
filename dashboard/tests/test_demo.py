# Проверка на данных, где ответ известен заранее:
# в демо-наборе заложены проблемные стажёры, дашборд должен их найти и не поднять лишних тревог.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import comments, db, ingest, metrics  # noqa: E402
from core.config import DEMO_DIR  # noqa: E402

MUST_BE_RED = ["Кузнецов Илья", "Соколова Дарья", "Морозов Артём", "Волкова Анна", "Новикова Полина", "Егоров Максим"]
ONE_BAD_MONTH = "Лебедев Никита"


def build(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    ingest.ingest(conn, DEMO_DIR / "otvety_stazhery.csv", "intern")
    ingest.ingest(conn, DEMO_DIR / "otvety_nastavniki.csv", "mentor")
    comments.run(conn, use_llm=False)
    a = metrics.load(conn)
    mon = metrics.monthly(a)
    return conn, a, mon, metrics.risk_table(mon, metrics.comments(conn, a), a)


def test_planted_problems_found(tmp_path):
    *_, risk = build(tmp_path)
    lv = dict(zip(risk["intern"], risk["level"]))
    for name in MUST_BE_RED:
        assert lv[name] == "высокий", (name, lv[name])


def test_one_bad_month_is_not_red(tmp_path):
    *_, risk = build(tmp_path)
    lv = dict(zip(risk["intern"], risk["level"]))
    assert lv[ONE_BAD_MONTH] == "средний"


def test_few_false_alarms(tmp_path):
    *_, risk = build(tmp_path)
    normal = risk[~risk["intern"].isin(MUST_BE_RED + [ONE_BAD_MONTH])]
    assert (normal["level"] == "высокий").sum() == 0
    assert (normal["level"] == "низкий").mean() >= 0.8


def test_reload_makes_no_duplicates(tmp_path):
    conn, a, *_ = build(tmp_path)
    before = len(a)
    ingest.ingest(conn, DEMO_DIR / "otvety_stazhery.csv", "intern")
    assert len(metrics.load(conn)) == before


def test_llm_answer_is_checked():
    batch = [{"role": "intern", "text": "Сижу до ночи, устал"}]
    raw = 'Вот ответ: [{"id": 1, "sentiment": -5, "topics": ["нагрузка", "погода"], ' \
          '"signals": ["перегруз", "выдуманный"], "quote": "этого нет в тексте"}]'
    r = comments.parse_answer(raw, batch)[1]
    assert r["sentiment"] == -1.0
    assert r["topics"] == ["нагрузка"]
    # цитаты нет в тексте: сигнал выбрасывается и считается отклонённым
    assert r["signals"] == []
    assert r["quote"] == ""
    assert r["rejected"] == 1


def test_signal_kept_when_quote_is_real():
    batch = [{"role": "intern", "text": "Сижу до ночи, устал"}]
    raw = '[{"id": 1, "sentiment": -0.8, "topics": ["нагрузка"], "signals": ["перегруз"], "quote": "Сижу до ночи"}]'
    r = comments.parse_answer(raw, batch)[1]
    assert r["signals"] == ["перегруз"] and r["rejected"] == 0


def test_signal_dropped_when_quote_changes_original_case():
    batch = [{"role": "intern", "text": "Сижу до ночи, устал"}]
    raw = '[{"id": 1, "sentiment": -0.8, "topics": [], "signals": ["перегруз"], "quote": "сижу до ночи"}]'
    result = comments.parse_answer(raw, batch)[1]
    assert result["signals"] == [] and result["quote"] == ""


def test_signal_dropped_when_quote_is_empty():
    batch = [{"role": "intern", "text": "Сижу до ночи, устал"}]
    raw = '[{"id": 1, "sentiment": -0.8, "topics": [], "signals": ["перегруз"], "quote": ""}]'
    assert comments.parse_answer(raw, batch)[1]["signals"] == []


def test_new_model_reanalyzes_comments(tmp_path, monkeypatch):
    # разобрали словарём; потом подключили нейросеть — комментарии должны разобраться заново
    conn = db.connect(tmp_path / "v.db")
    ingest.ingest(conn, DEMO_DIR / "otvety_stazhery.csv", "intern")
    first = comments.run(conn)
    assert first["словарь"] == first["всего"] > 0
    assert comments.run(conn)["всего"] == 0  # ничего не поменялось — ничего не пересчитываем

    monkeypatch.setattr(comments.llm, "name", lambda: "тест-модель")
    calls = []

    def fake_llm(batch, names=()):
        calls.append(len(batch))
        return {i: {"sentiment": 0.0, "topics": [], "signals": [], "quote": "", "rejected": 0} for i in range(1, len(batch) + 1)}

    monkeypatch.setattr(comments, "by_llm", fake_llm)
    second = comments.run(conn)
    assert second["всего"] == first["всего"] and second["нейросеть"] > 0 and calls
    assert comments.run(conn)["всего"] == 0

    monkeypatch.setattr(comments, "PROMPT_VERSION", "другой-промпт")
    assert comments.run(conn)["всего"] == first["всего"]  # поменяли промпт — снова пересчёт


def test_playbook_picks_action(tmp_path):
    # для каждой заложенной истории дашборд должен предложить подходящее действие
    from core import playbook
    *_, risk = build(tmp_path)
    expected = {
        "Кузнецов Илья": "leave", "Новикова Полина": "leave", "Соколова Дарья": "no_mentor",
        "Волкова Анна": "silent", "Морозов Артём": "no_tasks", "Егоров Максим": "results",
        "Лебедев Никита": "overload",
    }
    for r in risk.itertuples():
        act = playbook.action(r.intern, "Белов А.", r.codes, r.level, 5)
        if r.intern in expected:
            assert act["code"] == expected[r.intern], (r.intern, act["code"])
            for _, text in act["messages"]:
                assert "{" not in text  # все подстановки заполнены
        elif r.level == "низкий":
            assert act is None


def test_quote_is_from_real_comment(tmp_path):
    from core import playbook
    conn, a, mon, risk = build(tmp_path)
    com = metrics.comments(conn, a)
    q = playbook.best_quote(com[com["intern"] == "Новикова Полина"], 5)
    assert q["who"] == "стажёр" and "оффер" in q["quote"]
    texts = " ".join(com["text"].fillna(""))
    assert q["quote"] in texts


def test_stale_quote_cannot_keep_comment_signal(tmp_path):
    conn = db.connect(tmp_path / "stale-quote.db")
    rows, _ = ingest.to_rows(ingest.pd.DataFrame([{
        "ФИО стажёра": "Тестов Тест", "Месяц стажировки": 1,
        "Что мешало или что хочется изменить?": "Сижу до ночи",
    }]), "intern")
    ingest.save(conn, rows)
    digest = comments.text_hash("intern", "Сижу до ночи")
    conn.execute(
        "insert into comment_ai (hash, sentiment, topics, signals, quote, source, version) values (?,?,?,?,?,?,?)",
        (digest, -0.5, "[]", '["перегруз"]', "устал", "старая версия", "old"),
    )
    conn.commit()

    result = metrics.comments(conn, metrics.load(conn)).iloc[0]
    assert result["signals"] == [] and result["quote"] == ""


def test_effect_math():
    from core import effect
    parts, loss = effect.loss_per_intern(pay=40000, months=4, mentor_hours=4, mentor_rate=1500, rehire=60000)
    assert parts == {"Выплаты стажёру": 160000, "Время наставника": 96000, "Повторный набор": 60000}
    assert loss == 316000
    res = effect.summary(loss, at_risk=6, keep_share=0.3, ai=10, server_month=3000)
    assert round(res["kept"], 1) == 1.8 and round(res["saved"]) == 568800 and res["cost"] == 18010
    assert effect.ai_cost(0, 0, 0.8) == 0


def test_slow_decline_rule():
    # каждый месяц чуть хуже: разового падения нет, но за три месяца набегает больше 0.8
    import pandas as pd
    from core.metrics import risk_one
    cols = {"m_avg": None, "s_nps": None, "s_stay": None, "m_hire": None, "m_time": None}
    com = pd.DataFrame(columns=["month", "role", "signals", "sentiment"])
    slow = pd.DataFrame([{"intern": "x", "month": i + 1, "s_avg": v, **cols} for i, v in enumerate([4.6, 4.3, 4.0, 3.7])])
    flat = pd.DataFrame([{"intern": "x", "month": i + 1, "s_avg": v, **cols} for i, v in enumerate([4.6, 4.5, 4.6, 4.4])])
    assert any("три месяца подряд" in t for _, t in risk_one(slow, com, 4)[1])
    assert not any("три месяца подряд" in t for _, t in risk_one(flat, com, 4)[1])


def test_mentor_own_overload_is_not_intern_overload():
    r = comments.by_dictionary("Физически не успеваю заниматься стажёрами", "mentor")
    assert r["signals"] == ["нет поддержки наставника"]
    assert comments.by_dictionary("Роста не вижу", "mentor")["signals"] == []


def test_mask_replaces_whole_words_only():
    names = ["Тарасова Ева", "Белов А."]
    assert comments.mask("Не успеваю проверять", names) == "Не успеваю проверять"
    assert comments.mask("Ева опять опоздала, Белову сказали", names) == "[имя] опять опоздала, [имя] сказали"


def test_redacted_quote_matches_redacted_comment():
    names = ["Белов А.", "Тестов Тест"]
    text = "Белову не хватает времени, чтобы проверить работу"
    quote = comments.mask("Белову не хватает времени", names)
    shown_text = comments.mask(text, names)
    assert quote in shown_text


def test_rejected_signal_gets_second_try(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "r.db")
    rows, _ = ingest.to_rows(ingest.pd.DataFrame([{"ФИО стажёра": "Тестов Тест", "Месяц стажировки": 1,
                                                   "Что мешало или что хочется изменить?": "Думаю уходить"}]), "intern")
    ingest.save(conn, rows)
    monkeypatch.setattr(comments.llm, "name", lambda: "тест-модель")
    answers = iter([
        '[{"id": 1, "sentiment": -0.9, "topics": [], "signals": ["хочет уйти"], "quote": ""}]',              # без цитаты
        '[{"id": 1, "sentiment": -0.9, "topics": [], "signals": ["хочет уйти"], "quote": "Думаю уходить"}]',  # со второй попытки
    ])
    monkeypatch.setattr(comments.llm, "chat", lambda *a, **k: next(answers))
    st = comments.run(conn)
    assert st["повторно"] == 1 and st["отклонено проверкой"] == 0
    com = metrics.comments(conn, metrics.load(conn))
    assert com["signals"].iloc[0] == ["хочет уйти"]


def test_two_sources_rule():
    from core.metrics import level
    assert level(80, ["оценки"]) == "средний"              # высокий балл, но только оценки
    assert level(55, ["оценки", "текст"]) == "высокий"
    assert level(10, ["текст"], leave=True) == "высокий"   # слова об уходе — сразу разговор
    assert level(30, ["оценки", "текст"]) == "средний"
    assert level(10, ["оценки"]) == "низкий"
