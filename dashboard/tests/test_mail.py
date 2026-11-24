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


def test_fetch_without_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("YANDEX_MAIL", raising=False)
    monkeypatch.delenv("YANDEX_APP_PASSWORD", raising=False)
    st = mail.fetch(db.connect(tmp_path / "n.db"))
    assert st["ответов"] == 0 and "YANDEX_MAIL" in st["ошибки"][0]
