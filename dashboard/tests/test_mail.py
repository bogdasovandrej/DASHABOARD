# Почтовый канал: письмо от формы -> ответ в базе. Настоящий ящик не нужен, его подменяет FakeBox.
import json
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, mail, metrics  # noqa: E402

ANSWER = {"ФИО стажёра": "Тестов Тест", "Подразделение": "Аналитика", "Наставник": "Белов А.",
          "Месяц стажировки": "2", "Нагрузка мне по силам": "2",
          "Что мешало или что хочется изменить?": "Сижу до ночи, не успеваю"}


def letter(subject, body, subtype="plain", mid="<1@test>"):
    m = EmailMessage()
    m["Subject"], m["Message-ID"] = subject, mid
    m.set_content(body, subtype=subtype)
    return m


def test_parse_plain_and_html():
    plain = letter("Ответ [intern]", "SEC=41\n" + json.dumps(ANSWER, ensure_ascii=False))
    role, row = mail.parse_message(plain)
    assert role == "intern" and row["ФИО стажёра"] == "Тестов Тест" and row["Время заполнения (сек)"] == 41
    # в HTML-письме кавычки приходят как &quot;, а вокруг теги
    body = "<p>Ответ:</p><div>" + json.dumps(ANSWER, ensure_ascii=False).replace('"', "&quot;") + "</div>"
    role, row = mail.parse_message(letter("[mentor] Ответ на форму", body, "html"))
    assert role == "mentor" and row["Нагрузка мне по силам"] == "2"


def test_foreign_letters_are_ignored():
    assert mail.parse_message(letter("Счёт за интернет", '{"a": 1}')) is None
    assert mail.parse_message(letter("[intern] без данных", "просто текст")) is None


def test_yandex_form_mail_from_both_roles_imports_to_isolated_db(tmp_path):
    # Структура письма проверена по двум контрольным ответам живых Яндекс Форм 25.11.
    surveys = [
        ("intern", "6afb375b90290223d2c3f6fe", {
            "answer_short_text_9008994103360844": "ТЕСТ Интеграция",
            "answer_choices_9008994300008000": [{"text": "2"}],
            "answer_choices_9008994300014000": [{"text": "2"}],
            "answer_long_text_9008994300030000": "ТЕСТ: нагрузка велика",
        }),
        ("mentor", "6afc661cba5f0233e5bffc38", {
            "answer_short_text_9008995300004000": "ТЕСТ Интеграция",
            "answer_choices_9008995300010000": [{"text": "2"}],
            "answer_choices_9008995300014000": [{"text": "3"}],
            "answer_long_text_9008995300028000": "ТЕСТ: нужно уточнить задачи",
        }),
    ]
    conn = db.connect(tmp_path / "yandex.db")
    for role, survey_id, values in surveys:
        body = {
            "survey_id": survey_id, "created": "2026-11-25T18:22:19Z",
            "answer": {"started": "2026-11-25T18:21:19Z",
                       "data": {slug: {"value": value, "question": {"slug": slug}}
                                for slug, value in values.items()}},
        }
        parsed_role, row = mail.parse_message(letter(f"[{role}] Ответ на анкету", json.dumps(body, ensure_ascii=False)))
        assert parsed_role == role
        assert row["ФИО стажёра"] == "ТЕСТ Интеграция"
        assert row["Месяц стажировки"] == "2"
        assert row["Время заполнения (сек)"] == 60
        from core import ingest
        import pandas as pd
        rows, unknown = ingest.to_rows(pd.DataFrame([row]), role)
        assert not unknown
        ingest.save(conn, rows)
    loaded = metrics.load(conn)
    assert set(loaded["role"]) == {"intern", "mentor"}
    assert set(loaded["month"]) == {2}


class FakeBox:
    letters = []

    def __init__(self, *a, **k):
        pass

    def login(self, user, password):
        assert user and password

    def select(self, *a, **k):
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        mark = criteria[-1].strip('"')
        nums = [str(i).encode() for i, m in enumerate(self.letters, 1) if mark in m["Subject"]]
        return "OK", [b" ".join(nums)]

    def fetch(self, num, what):
        return "OK", [(b"", self.letters[int(num) - 1].as_bytes())]

    def logout(self):
        pass


def test_fetch_takes_each_letter_once(tmp_path, monkeypatch):
    monkeypatch.setenv("YANDEX_MAIL", "test@yandex.ru")
    monkeypatch.setenv("YANDEX_APP_PASSWORD", "x")
    FakeBox.letters = [letter("[intern] ответ", json.dumps(ANSWER, ensure_ascii=False), mid="<a@t>"),
                       letter("реклама", "{}", mid="<b@t>")]
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeBox)
    conn = db.connect(tmp_path / "m.db")
    first = mail.fetch(conn, use_llm=False)
    assert first["ответов"] == 1 and not first["ошибки"]
    assert mail.fetch(conn, use_llm=False)["ответов"] == 0  # то же письмо второй раз не берём
    com = metrics.comments(conn, metrics.load(conn))
    assert com["signals"].iloc[0] == ["перегруз"]


def test_fetch_yandex_json_for_both_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("YANDEX_MAIL", "test@yandex.ru")
    monkeypatch.setenv("YANDEX_APP_PASSWORD", "x")
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", FakeBox)
    fields = [
        ("intern", "6afb375b90290223d2c3f6fe", "answer_short_text_9008994103360844",
         "answer_choices_9008994300008000", "answer_choices_9008994300014000"),
        ("mentor", "6afc661cba5f0233e5bffc38", "answer_short_text_9008995300004000",
         "answer_choices_9008995300010000", "answer_choices_9008995300014000"),
    ]
    FakeBox.letters = []
    for role, survey_id, person, month, score in fields:
        payload = {"survey_id": survey_id, "created": "2026-11-25T18:22:19Z",
                   "answer": {"started": "2026-11-25T18:21:19Z", "data": {
                       person: {"value": "ТЕСТ Пара"},
                       month: {"value": [{"text": "2"}]},
                       score: {"value": [{"text": "3"}]},
                   }}}
        FakeBox.letters.append(letter(f"[{role}] Ответ на анкету",
                                      json.dumps(payload, ensure_ascii=False), mid=f"<{role}@test>"))
    conn = db.connect(tmp_path / "live-shape.db")
    result = mail.fetch(conn, use_llm=False)
    assert result["ответов"] == 2 and not result["ошибки"]
    assert set(metrics.load(conn)["role"]) == {"intern", "mentor"}
    assert mail.fetch(conn, use_llm=False)["ответов"] == 0


def test_fetch_without_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("YANDEX_MAIL", raising=False)
    monkeypatch.delenv("YANDEX_APP_PASSWORD", raising=False)
    st = mail.fetch(db.connect(tmp_path / "n.db"))
    assert st["ответов"] == 0 and "YANDEX_MAIL" in st["ошибки"][0]


def test_parse_default_yandex_plain_text_mgts(monkeypatch):
    monkeypatch.setenv("QUESTIONS_CSV", "survey/questions_mgts.csv")
    body = (
        "ID стажера: СТ-006\n"
        "Подразделение / направление стажировки: IT\n"
        "Контрольный период: Месяц 6\n"
        "Понятность задач: 2\n"
        "Поддержка и обратная связь наставника: 2\n"
        "Комфортность нагрузки: 3\n"
        "Сложности за период: Высокая нагрузка и редкая обратная связь.\n"
    )
    msg = letter("[intern] Ответ на анкету", body)
    msg["Date"] = "Thu, 26 Nov 2026 10:25:00 +0300"
    role, row = mail.parse_message(msg)
    assert role == "intern"
    assert row["ID стажера"] == "СТ-006"
    assert row["Понятность задач"] == "2"
    assert row["Время отправки"].startswith("2026-11-26T10:25:00")
