# Проверка финального кейса МГТС: 5 стажёров (СТ-001..СТ-005), 5 наставников (Н-001..Н-005), 6 месяцев.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import comments, db, ingest, metrics  # noqa: E402


def load_mgts(tmp_path, monkeypatch):
    monkeypatch.setenv("QUESTIONS_CSV", "survey/questions_mgts.csv")
    monkeypatch.setenv("DEMO_DIR", "data/mgts")
    conn = db.connect(tmp_path / "mgts.db")
    r_int = ingest.ingest(conn, ROOT / "data" / "mgts" / "otvety_stazhery.csv", "intern")
    r_men = ingest.ingest(conn, ROOT / "data" / "mgts" / "otvety_nastavniki.csv", "mentor")
    assert not r_int["нераспознанные колонки"]
    assert not r_men["нераспознанные колонки"]
    assert r_int["анкет принято"] == 30
    assert r_men["анкет принято"] == 30
    comments.run(conn, use_llm=False)
    a = metrics.load(conn)
    mon = metrics.monthly(a)
    com = metrics.comments(conn, a)
    return conn, a, mon, com


def test_mgts_ids_mentors_and_status(tmp_path, monkeypatch):
    _, a, mon, _ = load_mgts(tmp_path, monkeypatch)
    ppl = metrics.people(a).set_index("intern")
    assert set(ppl.index) == {"СТ-001", "СТ-002", "СТ-003", "СТ-004", "СТ-005"}
    assert ppl.loc["СТ-003", "mentor"] == "Н-003"
    assert ppl.loc["СТ-005", "dept"] == "IT"

    st = metrics.survey_status(a, 6)
    assert len(st) == 5
    assert (st["Опрос стажёра"] == "Сдал").all()
    assert (st["Опрос наставника"] == "Сдал").all()


def test_mgts_catches_month3_crisis_and_month4_overload(tmp_path, monkeypatch):
    _, a, mon, com = load_mgts(tmp_path, monkeypatch)

    # Месяц 3: СТ-003 в кризисе (высокий приоритет), СТ-005 — нехватка поддержки и расхождение по задачам
    r3 = metrics.risk_table(mon, com, a, last_month=3).set_index("intern")
    assert r3.loc["СТ-003", "level"] == "высокий"
    assert r3.loc["СТ-005", "level"] in ("высокий", "средний")
    assert r3.loc["СТ-001", "level"] == "низкий"
    assert r3.loc["СТ-002", "level"] == "низкий"

    # Парное расхождение СТ-005 в 1–2 месяце: Понятность задач 2.0 vs Понимание задач 4.0 (-2.0)
    pg = metrics.paired_gaps(a, "СТ-005", 2).set_index("Аспект")
    assert pg.loc["Задачи", "Разница"] == -2.0

    # Месяц 4: СТ-004 скрытый перегруз (средняя 4.4, но комфорт нагрузки = 2 + текст перегруза)
    r4 = metrics.risk_table(mon, com, a, last_month=4).set_index("intern")
    assert r4.loc["СТ-004", "level"] in ("высокий", "средний")
    assert "overload" in r4.loc["СТ-004", "codes"]

    # Месяц 6: все 5 восстановились до позитивной зоны
    r6 = metrics.risk_table(mon, com, a, last_month=6).set_index("intern")
    assert (r6["level"] == "низкий").all()


def test_mgts_new_response_updates_status_and_triggers_alert(tmp_path, monkeypatch):
    conn, _, _, _ = load_mgts(tmp_path, monkeypatch)
    # Имитируем приход нового ответа от СТ-006 только от стажёра (наставник ещё не сдал)
    row = {
        "ID стажера": "СТ-006",
        "Подразделение / направление стажировки": "IT",
        "Контрольный период": "Месяц 6",
        "Понятность задач": "2",
        "Поддержка и обратная связь наставника": "2",
        "Комфортность нагрузки": "2",
        "Интерес к задачам": "3",
        "Профессиональное развитие": "3",
        "Взаимодействие с командой": "3",
        "Общая удовлетворенность стажировкой": "2",
        "Сложности за период": "Высокая нагрузка и не хватает регулярной обратной связи от наставника.",
        "Что мешает работать и развиваться": "Смотрю вакансии в другую компанию.",
    }
    rows, unknown = ingest.to_rows(ingest.pd.DataFrame([row]), "intern")
    assert not unknown
    ingest.save(conn, rows)
    comments.run(conn, use_llm=False)

    a = metrics.load(conn)
    mon = metrics.monthly(a)
    com = metrics.comments(conn, a)
    st6 = metrics.survey_status(a, 6).set_index("ID стажёра")
    assert st6.loc["СТ-006", "Опрос стажёра"] == "Сдал"
    assert st6.loc["СТ-006", "Опрос наставника"] == "Нет ответа"

    r6 = metrics.risk_table(mon, com, a, last_month=6).set_index("intern")
    assert r6.loc["СТ-006", "level"] == "высокий"


def test_model_signals_require_auditable_text_evidence():
    missed = comments.checked_model_result(
        "Мешают неясные задачи и редкая обратная связь.", "intern",
        {"sentiment": -0.3, "topics": ["задачи"], "signals": [], "quote": ""},
    )
    assert missed["signals"] == ["нет поддержки наставника"]
    assert missed["quote"] == "Мешают неясные задачи и редкая обратная связь."

    invented = comments.checked_model_result(
        "Технически сильный, но нуждается в помощи по организации работы.", "mentor",
        {"sentiment": 0, "topics": ["задачи"], "signals": ["нет поддержки наставника"],
         "quote": "нуждается в помощи по организации работы"},
    )
    assert invented["signals"] == []
    assert invented["quote"] == ""
