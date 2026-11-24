# Загрузка ответов. Сервисы анкет отдают "широкую" таблицу: строка = одна анкета, колонка = вопрос.
# Здесь она превращается в длинную: строка = ответ на один вопрос.
# Все оценки сразу приводятся к шкале от 1 до 5, где 5 всегда хорошо. Тогда расчётам всё равно,
# какая шкала была в анкете и в какую сторону задан вопрос.
import hashlib
import json
import re

import pandas as pd

from .config import questions_csv

SUPPORTED_ROLES = {"any", "intern", "mentor"}
SUPPORTED_KINDS = {"meta", "scale", "nps", "text", "time"}
MAX_MONTH = 6


def norm(s):
    s = str(s).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", " ", s).strip()


def clean_name(s):
    # "  кузнецов   илья " и "КУЗНЕЦОВ ИЛЬЯ" должны стать одним человеком
    s = " ".join(str(s).split())
    return s.title() if s.islower() or s.isupper() else s


def load_questions(path=None):
    q = pd.read_csv(path or questions_csv(), dtype=str).fillna("")
    required = {"id", "role", "kind", "column"}
    missing = sorted(required - set(q.columns))
    if missing:
        raise ValueError(f"В файле вопросов не хватает колонок: {', '.join(missing)}")
    if q.empty:
        raise ValueError("Файл сопоставления вопросов пустой.")

    for col in ["id", "role", "kind", "column"]:
        q[col] = q[col].astype(str).str.strip()
        if q[col].eq("").any():
            raise ValueError(f"В файле вопросов есть пустые значения в колонке «{col}».")
    q["role"] = q["role"].str.lower()
    q["kind"] = q["kind"].str.lower()
    bad_roles = sorted(set(q.loc[~q["role"].isin(SUPPORTED_ROLES), "role"]))
    if bad_roles:
        raise ValueError(f"Неизвестные роли в файле вопросов: {', '.join(bad_roles)}")
    bad_kinds = sorted(set(q.loc[~q["kind"].isin(SUPPORTED_KINDS), "kind"]))
    if bad_kinds:
        raise ValueError(f"Неизвестные типы вопросов: {', '.join(bad_kinds)}")
    repeated_ids = sorted(q.loc[q["id"].duplicated(keep=False), "id"].unique())
    if repeated_ids:
        raise ValueError(f"Повторяются id вопросов: {', '.join(repeated_ids)}")

    for col in ["min", "max", "reverse", "block"]:
        if col not in q:
            q[col] = ""
    if "avg" not in q:
        q["avg"] = "0"
    for col in ["avg", "reverse"]:
        q[col] = pd.to_numeric(q[col].replace("", "0"), errors="coerce")
        if q[col].isna().any() or not q[col].isin([0, 1]).all():
            raise ValueError(f"В колонке «{col}» разрешены только 0 и 1.")
        q[col] = q[col].astype(int)
    if ((q["avg"] == 1) & (q["kind"] != "scale")).any():
        raise ValueError("В среднее месяца можно включать только вопросы типа scale.")
    if ((q["reverse"] == 1) & (q["kind"] != "scale")).any():
        raise ValueError("Обратными можно помечать только вопросы типа scale.")

    # NPS бывает от 0 до 10; обычные оценки по умолчанию идут от 1 до 5.
    default_min = q["kind"].map(lambda kind: 0 if kind == "nps" else 1)
    default_max = q["kind"].map(lambda kind: 10 if kind == "nps" else 5)
    for col, defaults in [("min", default_min), ("max", default_max)]:
        raw = q[col].astype(str).str.strip()
        parsed = pd.to_numeric(raw.replace("", pd.NA), errors="coerce")
        invalid = raw.ne("") & parsed.isna()
        if invalid.any():
            raise ValueError(f"В колонке «{col}» есть нечисловые границы шкалы.")
        q[col] = parsed.fillna(defaults)
    ranged = q["kind"].isin(["scale", "nps"])
    if (q.loc[ranged, "max"] <= q.loc[ranged, "min"]).any():
        raise ValueError("У шкал в файле вопросов верхняя граница должна быть выше нижней.")
    nps = q["kind"] == "nps"
    if (nps & (~q["min"].isin([0, 1]) | (q["max"] != 10))).any():
        raise ValueError("Для вопроса eNPS укажите шкалу 0–10 или 1–10: расчёт использует границы 0–6 и 9–10.")

    q["key"] = q["column"].map(norm)
    if q["key"].eq("").any():
        raise ValueError("В файле вопросов есть пустые названия колонок.")

    for role in ["intern", "mentor"]:
        applicable = q[q["role"].isin(["any", role])]
        missing_meta = [key for key in ["intern", "month"]
                        if not ((applicable["id"] == key) & (applicable["kind"] == "meta")).any()]
        if missing_meta:
            raise ValueError(f"Для роли {role} не сопоставлены обязательные поля: {', '.join(missing_meta)}")
        if not ((applicable["kind"] == "scale") & (applicable["avg"] == 1)).any():
            raise ValueError(f"Для роли {role} нужен хотя бы один вопрос типа scale в среднем за месяц.")

    for key, group in q.groupby("key"):
        roles = group["role"].tolist()
        overlaps = len(roles) > 1 and ("any" in roles or len(roles) != len(set(roles)))
        if overlaps:
            raise ValueError(f"Колонка «{key}» сопоставлена нескольким вопросам одной роли.")
    return q


def to_five(value, lo, hi, reverse):
    # перевод оценки в шкалу 1-5. Обратный вопрос ("нагрузка слишком высокая") переворачиваем.
    value = min(max(value, lo), hi)
    x = 1 + (value - lo) / (hi - lo) * 4
    return round(6 - x if reverse else x, 2)


def read_export(src, sheet=0):
    # src: путь к файлу, загруженный файл из Streamlit или ссылка на csv. sheet: лист Excel, номер или название
    name = str(getattr(src, "name", src)).lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(src, dtype=str, sheet_name=sheet)
    if name.endswith(".json"):
        return pd.read_json(src, dtype=str)
    return pd.read_csv(src, dtype=str, sep=None, engine="python", encoding="utf-8-sig")


def to_rows(df, role, questions=None, stats=None, require_average=False):
    if role not in {"intern", "mentor"}:
        raise ValueError("Роль должна быть intern или mentor.")
    stats = stats if stats is not None else {}
    stats.update({"строк без ФИО или месяца": 0, "ответов с неверным значением": 0,
                  "ответов вне шкалы": 0, "строк с месяцем вне диапазона 1–6": 0})
    q = load_questions() if questions is None else questions
    q = q[q["role"].isin(["any", role])]
    by_key = {r.key: r for r in q.itertuples()}

    cols, unknown = {}, []
    for c in df.columns:
        r = by_key.get(norm(c))
        if r is None:
            unknown.append(c)
        else:
            cols[r.id] = (c, r)

    missing = [m for m in ["intern", "month"] if m not in cols]
    if missing:
        raise ValueError(f"В файле нет обязательных колонок: {missing}. Проверьте названия в файле сопоставления вопросов")

    answer_cols = [(col, r) for col, r in cols.values() if r.kind not in {"meta", "time"}]
    if not answer_cols:
        examples = ", ".join(str(c) for c in unknown[:8])
        detail = f" Неузнанные колонки: {examples}." if examples else ""
        raise ValueError(
            "Не нашёл в файле колонок с ответами для выбранной роли. "
            f"Проверьте лист и файл сопоставления вопросов.{detail}"
        )
    if require_average:
        expected_averages = q[(q["kind"] == "scale") & (q["avg"] == 1)]
        if not any(question_id in cols for question_id in expected_averages["id"]):
            raise ValueError(f"В файле нет распознанных оценочных колонок для роли {role}; динамика не рассчитается.")

    def meta(row, key):
        return str(row[cols[key][0]]).strip() if key in cols and pd.notna(row[cols[key][0]]) else ""

    rows = []
    for _, row in df.iterrows():
        intern = clean_name(meta(row, "intern"))
        m = re.search(r"\d+", meta(row, "month"))
        if not intern or not m:
            stats["строк без ФИО или месяца"] += 1
            continue
        month = int(m.group())
        if not 1 <= month <= MAX_MONTH:
            stats["строк с месяцем вне диапазона 1–6"] += 1
            continue
        start = len(rows)
        has_answer = False
        for qid, (col, r) in cols.items():
            if r.kind == "meta":
                continue
            val = row[col]
            if pd.isna(val) or str(val).strip() == "":
                continue
            score, text = None, None
            if r.kind == "text":
                text = str(val).strip()
            else:
                raw = str(val).strip().lower()
                try:
                    # вопросы "Да/Нет" считаем как края шкалы
                    score = r.max if raw == "да" else r.min if raw == "нет" else float(raw.replace(",", "."))
                except ValueError:
                    stats["ответов с неверным значением"] += 1
                    continue
                if r.kind == "scale":
                    if score < r.min or score > r.max:
                        stats["ответов вне шкалы"] += 1
                        continue
                    score = to_five(score, r.min, r.max, r.reverse)
                elif r.kind == "nps" and (score < r.min or score > r.max):
                    stats["ответов вне шкалы"] += 1
                    continue
            # uid одинаковый при повторной загрузке, поэтому дубли не появляются
            uid = hashlib.sha1(f"{role}|{intern}|{month}|{qid}".encode()).hexdigest()
            rows.append((uid, role, intern, meta(row, "dept"), clean_name(meta(row, "mentor")), month, qid, score, text, meta(row, "ts")))
            has_answer |= r.kind != "time"
        if not has_answer:
            del rows[start:]
    if not rows:
        skipped = ", ".join(f"{key}: {value}" for key, value in stats.items() if value)
        detail = f" Пропуски: {skipped}." if skipped else ""
        raise ValueError(
            "Не удалось извлечь ни одного ответа. Проверьте, что в строках заполнены "
            "ФИО стажёра и месяц, а в ответах есть значения из шкалы или текст."
            f"{detail}"
        )
    return rows, unknown


def flatten_answer(body):
    # Сводим ответ к виду {"название вопроса": ответ}. Точный формат Яндекса проверим на живом запросе,
    # поэтому понимаем несколько вариантов: плоский словарь, список {вопрос, ответ}, вложенность в "answers"/"data".
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        for key in ("answers", "data", "params", "answer"):
            if key in body and isinstance(body[key], (dict, list, str)):
                inner = flatten_answer(body[key])
                if inner:
                    return {**{k: v for k, v in body.items() if not isinstance(v, (dict, list))}, **inner}
    items = body.items() if isinstance(body, dict) else enumerate(body if isinstance(body, list) else [])
    out = {}
    for key, val in items:
        if isinstance(val, dict):
            q = val.get("question")
            label = (q.get("label") if isinstance(q, dict) else q) or val.get("label") or val.get("name") or key
            value = val.get("value", val.get("answer"))
        else:
            label, value = key, val
        if isinstance(value, list):
            value = ", ".join(str(v.get("text", v)) if isinstance(v, dict) else str(v) for v in value)
        elif isinstance(value, dict):
            value = value.get("text", value.get("value", ""))
        out[str(label)] = value
    return out


def save(conn, rows):
    conn.executemany("insert or replace into answers values (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def ingest(conn, src, role, sheet=0):
    df = read_export(src, sheet)
    stats = {}
    rows, unknown = to_rows(df, role, stats=stats, require_average=True)
    save(conn, rows)
    return {"анкет": len(df), "анкет принято": len({(r[2], r[5]) for r in rows}),
            "ответов": len({r[0] for r in rows}), "нераспознанные колонки": unknown, **stats}
