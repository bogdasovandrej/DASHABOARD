import os
import sqlite3
from pathlib import Path

from .config import DB_PATH

# answers: одна строка = один ответ на один вопрос (длинный формат, так проще считать)
# actions: что HR отметил как сделанное
# comment_ai: результат разбора комментария, ключ = хэш текста, чтобы не разбирать одно и то же дважды.
#   version: чем разобран (модель + версия промпта или словарь). Сменилась модель или промпт — разбираем заново.
#   rejected: сколько сигналов выброшено, потому что модель не дала дословную цитату
SCHEMA = """
create table if not exists answers(
    uid text primary key,
    role text, intern text, dept text, mentor text, month integer,
    qid text, score real, text text, ts text
);
create table if not exists comment_ai(
    hash text primary key,
    sentiment real, topics text, signals text, quote text, source text,
    version text, rejected integer default 0
);
create table if not exists actions(
    intern text, month integer, title text, done_at text
);
"""


def connect(path=None):
    path = Path(path or os.getenv("DB_PATH") or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    # базы, созданные до появления этих колонок, дополняем
    have = {r[1] for r in conn.execute("pragma table_info(comment_ai)")}
    for col, kind in [("version", "text"), ("rejected", "integer default 0")]:
        if col not in have:
            conn.execute(f"alter table comment_ai add column {col} {kind}")
    return conn


def add_action(conn, intern, month, title):
    conn.execute("insert into actions values (?,?,?,datetime('now','localtime'))", (intern, int(month), title))
    conn.commit()


def actions(conn):
    import pandas as pd
    return pd.read_sql("select * from actions order by done_at desc", conn)


def clear(conn):
    conn.execute("delete from actions")
    conn.execute("delete from answers")
    conn.execute("delete from comment_ai")
    conn.commit()
