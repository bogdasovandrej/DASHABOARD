# Все расчёты: средние по месяцам, eNPS и риск по каждому стажёру.
# Риск считается простыми правилами с баллами. Модель машинного обучения тут не нужна:
# на одного стажёра максимум шесть опросов, учить не на чем, а правила можно объяснить HR.
import json

import pandas as pd

from . import comments as comment_tools, config as c
from .comments import EMPTY, simple, text_hash
from .ingest import load_questions


def load(conn):
    a = pd.read_sql("select * from answers", conn)
    q = load_questions()[["id", "kind", "avg", "short", "block"]]
    return a.merge(q, left_on="qid", right_on="id", how="left").drop(columns="id")


# Особые вопросы находим по роли, типу и блоку из файла сопоставления, а не по нашим названиям.
# Так расчёты работают и с чужой анкетой.
SPECIAL = {
    "s_nps": ("intern", "nps", None),             # рекомендация 0-10
    "s_stay": ("intern", "scale", "будущее"),     # хочет остаться
    "m_hire": ("mentor", "scale", "штат"),        # наставник рекомендует в штат
    "m_time": ("mentor", "scale", "время наставника"),
}


def pick(a, role, kind, block=None):
    m = (a["role"] == role) & (a["kind"] == kind)
    return a[m & (a["block"] == block)] if block else a[m]


def monthly(a):
    # одна строка на стажёра и месяц: средняя оценка стажёра, средняя оценка наставника и особые вопросы
    periods = a.loc[a["kind"].notna() & a["kind"].ne("time"), ["intern", "month"]]
    sc = a[a["kind"] == "scale"]
    avg = sc[sc["avg"] == 1].pivot_table(index=["intern", "month"], columns="role", values="score", aggfunc="mean")
    out = periods.drop_duplicates().set_index(["intern", "month"])
    out = out.join(avg.rename(columns={"intern": "s_avg", "mentor": "m_avg"}))
    for name, (role, kind, block) in SPECIAL.items():
        out = out.join(pick(a, role, kind, block).groupby(["intern", "month"])["score"].mean().rename(name))
    out = out.reset_index()
    for col in ["s_avg", "m_avg"]:
        if col not in out:
            out[col] = float("nan")
    out.columns.name = None
    return out


def people(a):
    return a.sort_values("month").groupby("intern")[["dept", "mentor"]].last().reset_index()


def comments(conn, a):
    t = a[a["kind"] == "text"][["intern", "month", "role", "qid", "short", "text"]].copy()
    if t.empty:
        return t.assign(sentiment=[], topics=[], signals=[], quote=[], source=[])
    t["hash"] = [text_hash(r, x) for r, x in zip(t["role"], t["text"])]
    ai = pd.read_sql("select * from comment_ai", conn)
    t = t.merge(ai, on="hash", how="left")
    for col in ["topics", "signals"]:
        t[col] = t[col].map(lambda v: json.loads(v) if isinstance(v, str) else [])
    t["quote"] = t["quote"].fillna("")
    people = set(a["intern"].dropna().astype(str)) | set(a["mentor"].dropna().astype(str))
    # Старые или повреждённые результаты не могут поднять сигнал без цитаты,
    # которую HR найдёт в исходном комментарии или в его версии с замаскированными именами.
    for i, row in t.iterrows():
        quote = row["quote"]
        if row["signals"] and (not quote or (quote not in row["text"] and quote not in comment_tools.mask(row["text"], people))):
            t.at[i, "signals"] = []
            t.at[i, "quote"] = ""
    return t


def quality(a):
    # Можно ли верить анкете стажёра. Оценки "всё на пять" без текста за 20 секунд ничего не говорят,
    # поэтому такую анкету помечаем как формальную: это не "всё хорошо", а "мы не знаем".
    rows = []
    s = a[(a["role"] == "intern") & a["kind"].notna()]
    for (intern, month), g in s.groupby(["intern", "month"]):
        if g["kind"].eq("time").all():
            continue
        notes = []
        sc = g[g["kind"] == "scale"]["score"]
        if len(sc) >= 4 and sc.nunique() == 1:
            notes.append(f"все оценки одинаковые ({sc.iloc[0]:.0f})")
        texts = [t for t in g[g["kind"] == "text"]["text"].fillna("")]
        chars = sum(len(t) for t in texts if simple(t) not in EMPTY)
        if chars < 15:
            notes.append("нет содержательного комментария")
        sec = g[g["kind"] == "time"]["score"]
        if len(sec) and sec.iloc[0] < c.FAST_SEC:
            notes.append(f"заполнена за {sec.iloc[0]:.0f} сек")
        rows.append({"intern": intern, "month": month, "notes": notes, "formal": len(notes) >= 2, "chars": chars})
    return pd.DataFrame(rows, columns=["intern", "month", "notes", "formal", "chars"])


def enps(mon, month):
    s = mon[mon["month"] == month]["s_nps"].dropna()
    if s.empty:
        return None
    return round(((s >= 9).mean() - (s <= 6).mean()) * 100)


# какой блок анкеты и какой сигнал из текста к какой проблеме относится
BLOCK_CODE = {"нагрузка": "overload", "наставник": "no_mentor", "задачи": "no_tasks", "развитие": "no_tasks"}
SIGNAL_CODE = {"перегруз": "overload", "мало задач": "no_tasks", "нет поддержки наставника": "no_mentor",
               "конфликт": "conflict", "слабые результаты": "results", "потеря интереса": "low"}


# Откуда взялся признак. Тревогу «поговорить» поднимаем, только когда признаки пришли минимум из двух
# разных источников: одна плохая цифра или одна фраза может быть случайностью, совпадение двух — уже нет.
SCORES, TEXT, BEHAVIOR = "оценки", "текст", "поведение"


def level(score, sources=(), leave=False):
    # Прямые слова об уходе — разговор сразу, независимо от остального
    if leave:
        return "высокий"
    if score >= c.RED and len(set(sources)) >= 2:
        return "высокий"
    if score >= c.YELLOW:
        return "средний"
    return "низкий"


def risk_one(m, com, last_month, q=None, ql=None):
    # m: строки monthly одного стажёра, com: его комментарии, q: его оценки по отдельным вопросам.
    # Возвращает (балл, причины с баллами, коды причин). По кодам потом выбирается действие для HR.
    m = m.sort_values("month")
    s = m.dropna(subset=["s_avg"])
    score, why = 0, []

    def add(points, text, *codes, src):
        nonlocal score
        score += points
        why.append((points, text, codes, src))

    received = ql if ql is not None else s
    if last_month not in received["month"].values:
        add(20, f"не заполнил анкету за {last_month}-й месяц", "silent", src=BEHAVIOR)

    if not s.empty:
        cur = s["s_avg"].iloc[-1]
        cur_month = int(s["month"].iloc[-1])
        prev = s["s_avg"].iloc[-3:-1]
        if cur < c.LOW:
            add(30, f"средняя оценка стажёра {cur:.1f} из 5 в {cur_month}-м месяце", "low", src=SCORES)
        elif cur < c.SO_SO:
            add(15, f"средняя оценка стажёра {cur:.1f} из 5 в {cur_month}-м месяце", "low", src=SCORES)
        if len(prev):
            drop = cur - prev.mean()
            if drop <= -c.DROP_BIG:
                add(25, f"оценка упала на {abs(drop):.1f} к прошлым месяцам", "low", src=SCORES)
            elif drop <= -c.DROP_SMALL:
                add(12, f"оценка снизилась на {abs(drop):.1f} к прошлым месяцам", "low", src=SCORES)
        # Медленное выгорание: каждый месяц чуть хуже. Разовое падение этим правилом не ловится.
        tail = s.tail(4)
        scores = tail["s_avg"]
        adjacent = tail["month"].diff().eq(1)
        if (len(tail) == 4 and adjacent.iloc[1:].all() and scores.diff().dropna().lt(0).all()
                and scores.iloc[0] - scores.iloc[-1] >= c.DROP_BIG):
            add(15, f"оценка снижается три месяца подряд, всего на {scores.iloc[0] - scores.iloc[-1]:.1f}", "low", src=SCORES)
        if adjacent.iloc[-1] and scores.iloc[-2:].lt(c.SO_SO).all():
            add(15, "низкая оценка держится второй месяц подряд", src=SCORES)

        # Средняя может прятать провал по одному вопросу, поэтому смотрим вопросы отдельно
        if q is not None and len(q):
            now = q[(q["month"] == cur_month) & (q["score"] <= 2)]
            before = q[(q["month"] == cur_month - 1) & (q["score"] <= 2)]
            if len(now):
                add(15, "оценки 1-2 по вопросам: " + ", ".join(now["short"]), *[BLOCK_CODE.get(b, "low") for b in now["block"]], src=SCORES)
                again = sorted(set(now["short"]) & set(before["short"]))
                if again:
                    add(10, "второй месяц подряд низко: " + ", ".join(again), src=SCORES)

    last = m[m["month"] == last_month]
    if not last.empty:
        r = last.iloc[0]
        if pd.notna(r["s_avg"]) and pd.notna(r["m_avg"]):
            gap = r["s_avg"] - r["m_avg"]
            if gap <= -c.GAP:
                add(15, f"наставник оценивает на {abs(gap):.1f} выше, чем себя чувствует стажёр", "hidden", src=SCORES)
            elif gap >= c.GAP:
                add(15, f"стажёр доволен, а наставник оценивает его на {gap:.1f} ниже", "results", src=SCORES)
        if pd.notna(r["m_avg"]) and r["m_avg"] < c.LOW:
            add(20, f"средняя оценка наставника {r['m_avg']:.1f} из 5", "results", src=SCORES)
        if pd.notna(r["m_hire"]) and r["m_hire"] <= 2:
            add(10, "наставник не готов рекомендовать в штат", "results", src=SCORES)
        low_nps = pd.notna(r["s_nps"]) and r["s_nps"] <= 6
        low_stay = pd.notna(r["s_stay"]) and r["s_stay"] <= 2
        if low_nps or low_stay:
            add(10, "не хочет оставаться или не рекомендует стажировку", src=SCORES)

    if ql is not None and len(ql):
        ql = ql.sort_values("month")
        f = ql.iloc[-1]
        if f["formal"]:
            add(8, f"анкета за {int(f['month'])}-й месяц заполнена формально: " + ", ".join(f["notes"]), "formal", src=BEHAVIOR)
            if len(ql) >= 2 and ql.iloc[-2]["month"] == f["month"] - 1 and ql.iloc[-2]["formal"]:
                add(8, "формальная анкета второй месяц подряд, реальной картины нет", src=BEHAVIOR)
        before = ql["chars"].iloc[:-1]
        if len(before) >= 2 and before.median() >= 30 and f["chars"] < 0.4 * before.median():
            add(6, "комментарии стали намного короче, чем раньше", src=BEHAVIOR)

    recent = com[com["month"] >= last_month - 1]
    signals = sorted({s for row in recent["signals"] for s in row})
    if "хочет уйти" in signals:
        add(50, "в комментарии есть намерение уйти", "leave", src=TEXT)
    others = [s for s in signals if s != "хочет уйти"]
    if others:
        add(min(20, 10 * len(others)), "сигналы в комментариях: " + ", ".join(others), *[SIGNAL_CODE.get(x, "low") for x in others], src=TEXT)
    mood = recent[(recent["role"] == "intern") & (recent["month"] == last_month)]["sentiment"]
    if len(mood.dropna()) and mood.mean() <= -0.4:
        add(10, "негативный тон комментариев за последний месяц", src=TEXT)

    why.sort(key=lambda x: -x[0])
    codes = list(dict.fromkeys(code for _, _, cs, _ in why for code in cs))
    sources = sorted({src for *_, src in why})
    return min(100, score), [(p, t) for p, t, _, _ in why], codes, sources


def risk_table(mon, com, a):
    last_month = int(mon["month"].max())
    qs = a[(a["role"] == "intern") & (a["avg"] == 1)]
    ql = quality(a)
    rows = []
    for intern, m in mon.groupby("intern"):
        score, parts, codes, sources = risk_one(m, com[com["intern"] == intern], last_month, qs[qs["intern"] == intern],
                              ql[ql["intern"] == intern])
        s = m.dropna(subset=["s_avg"]).sort_values("month")
        rows.append({
            "intern": intern,
            "score": score,
            "level": level(score, sources, "leave" in codes),
            "sources": sources,
            "why": [t for _, t in parts],
            "parts": parts,
            "codes": codes,
            "s_last": s["s_avg"].iloc[-1] if len(s) else None,
            "m_last": m.sort_values("month")["m_avg"].dropna().iloc[-1] if m["m_avg"].notna().any() else None,
        })
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def mentors(a, mon):
    # нагрузка наставников: сколько стажёров, как стажёры оценивают помощь, хватает ли наставнику времени
    last = int(mon["month"].max())
    cur = a[a["month"] == last]
    help_ = pick(cur, "intern", "scale", "наставник").groupby("mentor")["score"].mean()
    time_ = pick(cur, "mentor", "scale", "время наставника").groupby("mentor")["score"].mean()
    n = a.groupby("mentor")["intern"].nunique()
    out = pd.DataFrame({"стажёров": n, "помощь наставника": help_, "хватает времени": time_}).reset_index()
    return out.rename(columns={"mentor": "наставник"}).sort_values("хватает времени")
