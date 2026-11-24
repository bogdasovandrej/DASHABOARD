# Самопроверка тренировки. Запускать из папки dashboard в том же окне, где запускали дашборд
# (чтобы остались переменные QUESTIONS_CSV и DB_PATH):
#     python ..\trenirovka\proverka\proverit.py
# Скрипт сам читает вашу базу и ваш файл сопоставления и печатает, что получилось. Код можно не открывать.
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "dashboard"))
from core import db, ingest, llm, metrics

MUST = ["Тихонов Марк", "Орлова Кира", "Комаров Денис", "Соловьёва Эля", "Жданов Олег", "Давыдова Яна", "Гусева Алина"]
NOT_RED = "Белова Ника"
ONLY_LLM = "Захаров Пётр"

score, total = 0, 0


def check(ok, text, hint=""):
    global score, total
    total += 1
    score += bool(ok)
    print(("  [да]  " if ok else "  [НЕТ] ") + text + ("" if ok or not hint else f"\n         подсказка: {hint}"))


def cell(a, q, column, intern, month):
    # нормированная оценка стажёра по вопросу с таким названием колонки
    ids = q[q["key"] == ingest.norm(column)]["id"]
    if ids.empty:
        return None
    x = a[(a["qid"] == ids.iloc[0]) & (a["intern"] == intern) & (a["month"] == month)]["score"]
    return x.iloc[0] if len(x) else None


def main():
    print("Файл сопоставления:", os.getenv("QUESTIONS_CSV", "survey/questions.csv (по умолчанию)"))
    print("База:", os.getenv("DB_PATH", "data/dashboard.db (по умолчанию)"))
    conn = db.connect()
    q = ingest.load_questions()
    a = metrics.load(conn)
    a = a[a["kind"].notna()]
    if a.empty:
        sys.exit("В базе нет ответов по вашему файлу сопоставления. Загрузите оба листа через раздел «Данные».")
    mon = metrics.monthly(a)
    com = metrics.comments(conn, a)
    risk = metrics.risk_table(mon, com, a).merge(metrics.people(a), on="intern")
    lv = dict(zip(risk["intern"], risk["level"]))

    print("\n1. Загрузка")
    check(a["intern"].nunique() == 30, f"стажёров в базе {a['intern'].nunique()}, должно быть 30",
          "ФИО написаны по-разному или загружен не тот лист")
    n_s = a[a["role"] == "intern"].groupby(["intern", "month"]).ngroups
    n_m = a[a["role"] == "mentor"].groupby(["intern", "month"]).ngroups
    check(n_s == 148, f"анкет стажёров {n_s}, должно быть 148")
    check(n_m == 150, f"анкет наставников {n_m}, должно быть 150",
          "на листе наставников ФИО стажёра и наставника называются по-другому: нужны отдельные строки meta для role=mentor")
    check(lv and risk[risk["intern"] == "Орлова Кира"]["mentor"].iloc[0] == "Фомин Г." if "Орлова Кира" in lv else False,
          "у стажёров правильно определён наставник")

    print("\n2. Шкалы и обратные вопросы")
    t = mon[(mon["intern"] == "Тихонов Марк") & (mon["month"] == 3)]["s_avg"]
    check(len(t) and t.iloc[0] <= 3.4, "шкала стажёров 1-7 переведена верно", "у вопросов стажёра должны стоять min=1 и max=7")
    v = cell(a, q, "Оценка качества работы", "Давыдова Яна", 5)
    check(v is not None and v <= 2.5, "шкала наставников 1-10 переведена верно", "у вопросов наставника должны стоять min=1 и max=10")
    v = cell(a, q, "Я часто перерабатываю", "Гусева Алина", 5)
    check(v is not None and v <= 1.5, "вопрос «Я часто перерабатываю» перевёрнут", "reverse=1: высокая оценка здесь означает плохо")
    v = cell(a, q, "Задачи кажутся мне бессмысленными", "Комаров Денис", 5)
    check(v is not None and v <= 1.5, "вопрос «Задачи кажутся мне бессмысленными» перевёрнут", "reverse=1")
    v = cell(a, q, "Приходится переделывать работу за стажёром", "Давыдова Яна", 5)
    check(v is not None and v <= 1.5, "вопрос наставника про переделки перевёрнут", "reverse=1")
    v = cell(a, q, "Наставник давал обратную связь в этом месяце", "Орлова Кира", 5)
    check(v == 1, "ответы «Да/Нет» загружены как оценка", "kind=scale, шкалу можно не указывать: Да это 5, Нет это 1")

    print("\n3. Особые вопросы")
    last = mon[mon["month"] == mon["month"].max()]
    for col, name, hint in [("s_nps", "рекомендация 0-10", "kind=nps"), ("s_stay", "видит себя в компании", "block=будущее"),
                            ("m_hire", "наставник взял бы в команду", "block=штат"),
                            ("m_time", "время наставника на стажёра", "block=время наставника")]:
        check(col in last and last[col].notna().sum() >= 25, f"найден вопрос: {name}", hint)

    print("\n4. Кого нашёл дашборд (красная или жёлтая зона)")
    for name in MUST:
        check(lv.get(name) in ("высокий", "средний"), f"{name}: {lv.get(name, 'нет в базе')}")
    check(lv.get(NOT_RED) != "высокий", f"{NOT_RED} не в красной зоне: один плохой месяц по болезни не тревога")
    normal = risk[~risk["intern"].isin(MUST + [NOT_RED, ONLY_LLM])]
    extra = list(normal[normal["level"] == "высокий"]["intern"])
    check(not extra, "лишних красных нет" if not extra else f"лишние красные: {', '.join(extra)}")
    m = metrics.mentors(a, mon)
    check(len(m) and m.iloc[0]["наставник"] == "Фомин Г.", "самый загруженный наставник определён верно")

    print("\n5. Без баллов, для сведения")
    model = llm.name()
    print("  нейросеть:", model or "не подключена, комментарии разбирал словарь")
    print(f"  {ONLY_LLM}: {lv.get(ONLY_LLM)}. По цифрам у него всё хорошо, проблема только в тексте другими словами.")
    print("  Если он красный, значит нейросеть работает. Словарь его найти не может.")
    red = list(risk[risk["level"] == "высокий"]["intern"])
    print("  красная зона:", ", ".join(red) or "пусто")

    print(f"\nИтог: {score} из {total}")
    if score == total:
        print("Данные загружены правильно. Дальше: три находки для защиты и двухминутный рассказ.")


if __name__ == "__main__":
    main()
