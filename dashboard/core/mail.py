# Получение ответов из Яндекс Форм через почту.
# Форма после каждого заполнения шлёт письмо (интеграция «Почта»). В теме письма метка [intern] или [mentor],
# в тексте — ответы в JSON. Дашборд раз в минуту заходит в ящик по IMAP и забирает новые письма.
# Почему почта, а не прямой запрос: форма шлёт запросы только по IPv6 на публичный адрес, а у ноутбука его нет,
# туннели в российских сетях рвутся. Почта работает внутри Яндекса в любой сети и с любым VPN.
#
# Настройки в .env:
#   YANDEX_MAIL=имя@yandex.ru
#   YANDEX_APP_PASSWORD=пароль приложения (создаётся в id.yandex.ru, обычный пароль от почты не подходит)
import email
import html
import imaplib
import json
import os
import re
from datetime import date, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

import pandas as pd

from . import comments, ingest

HOST = "imap.yandex.ru"
ROLES = {"[intern]": "intern", "[mentor]": "mentor"}
LOOK_BACK_DAYS = 30  # письма старше не смотрим, чтобы проверка шла быстро


def subject_roles():
    return {
        os.getenv("YANDEX_SUBJECT_INTERN", "[intern]").lower(): "intern",
        os.getenv("YANDEX_SUBJECT_MENTOR", "[mentor]").lower(): "mentor",
    }


def configured():
    return bool(os.getenv("YANDEX_MAIL") and os.getenv("YANDEX_APP_PASSWORD"))


def ensure_table(conn):
    # какие письма уже забрали: по Message-ID, а не по отметке «прочитано» — HR может открыть письмо сам
    conn.execute("create table if not exists mail_seen(message_id text primary key, role text, taken_at text)")


def body_text(msg):
    # текст письма: берём простой текст, если его нет — HTML без тегов
    plain, rich = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() != "text":
            continue
        raw = part.get_payload(decode=True) or b""
        text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_subtype() == "plain" and plain is None:
            plain = text
        elif part.get_content_subtype() == "html" and rich is None:
            rich = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(plain if plain is not None else rich or "")


def extract_json(text):
    # в тексте письма ищем первый целый JSON: от первой { или [ до парной закрывающей скобки
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            return obj
        except json.JSONDecodeError:
            continue
    return None


def extract_seconds(text):
    # необязательная строка «SEC=37» в письме: время заполнения анкеты
    m = re.search(r"SEC\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def role_of(subject):
    s = subject.lower()
    return next((role for mark, role in subject_roles().items() if mark in s), None)


def extract_labeled_lines(text, role):
    # Поддержка стандартного текстового письма Яндекс Форм («Ответы на вопросы»):
    # строки вида «Понятность задач: 4» или вопрос на одной строке, ответ на следующей.
    q = ingest.load_questions()
    q = q[q["role"].isin(["any", role])]
    by_key = {r.key: r.column for r in q.itertuples()}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" in line:
            left, right = line.split(":", 1)
            col = by_key.get(ingest.norm(left))
            if col and right.strip():
                out[col] = right.strip()
                i += 1
                continue
        col = by_key.get(ingest.norm(line))
        if col and i + 1 < len(lines) and ingest.norm(lines[i + 1]) not in by_key:
            out[col] = lines[i + 1]
            i += 2
            continue
        i += 1
    return out or None


def parse_message(msg):
    # письмо -> (роль, строка ответа {вопрос: значение}) или None, если письмо не от формы
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    role = role_of(subject)
    if not role:
        return None
    text = body_text(msg)
    data = extract_json(text)
    if data is not None:
        row = ingest.flatten_answer(data)
    else:
        row = extract_labeled_lines(text, role)
        if not row:
            return None
    if not row.get("Время отправки") and msg.get("Date"):
        try:
            row["Время отправки"] = parsedate_to_datetime(msg["Date"]).isoformat()
        except (TypeError, ValueError):
            pass
    sec = extract_seconds(text)
    if sec is not None:
        row["Время заполнения (сек)"] = sec
    return role, row


def fetch(conn, use_llm=True):
    # Забирает новые письма формы и кладёт ответы в базу. Возвращает статистику.
    stats = {"писем": 0, "ответов": 0, "пропущено": 0, "ошибки": []}
    if not configured():
        stats["ошибки"].append("в .env не заданы YANDEX_MAIL и YANDEX_APP_PASSWORD")
        return stats
    ensure_table(conn)
    seen = {r[0] for r in conn.execute("select message_id from mail_seen")}
    since = (date.today() - timedelta(days=LOOK_BACK_DAYS)).strftime("%d-%b-%Y")
    try:
        box = imaplib.IMAP4_SSL(HOST, 993, timeout=20)
        box.login(os.getenv("YANDEX_MAIL"), os.getenv("YANDEX_APP_PASSWORD"))
        box.select("INBOX", readonly=True)  # только читаем: ничего в ящике не меняем
        for mark in subject_roles():
            _, found = box.search(None, "SINCE", since, "SUBJECT", f'"{mark}"')
            for num in found[0].split():
                _, data = box.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                mid = msg.get("Message-ID") or f"{mark}-{num.decode()}"
                if mid in seen:
                    continue
                stats["писем"] += 1
                parsed = parse_message(msg)
                if not parsed:
                    stats["пропущено"] += 1
                    continue
                role, row = parsed
                try:
                    rows, _ = ingest.to_rows(pd.DataFrame([row]), role)
                except ValueError as e:
                    stats["ошибки"].append(str(e)[:200])
                    continue
                try:
                    ingest.save(conn, rows)
                except ValueError as e:
                    stats["ошибки"].append(str(e)[:200])
                    continue
                conn.execute("insert or ignore into mail_seen values (?, ?, datetime('now','localtime'))", (mid, role))
                seen.add(mid)
                stats["ответов"] += 1
        box.logout()
    except (imaplib.IMAP4.error, OSError) as e:
        stats["ошибки"].append(f"не удалось зайти в почту: {e}"[:200])
    conn.commit()
    if stats["ответов"]:
        comments.run(conn, use_llm=use_llm)
    return stats
