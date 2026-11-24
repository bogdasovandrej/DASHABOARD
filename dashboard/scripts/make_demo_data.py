# Делает тестовые выгрузки опросов в data/demo, как будто их скачали из сервиса анкет.
# В данные специально заложены проблемные стажёры, чтобы проверять, что дашборд их находит.
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import DEMO_DIR, QUESTIONS_CSV

MONTHS = 5  # идёт пятый месяц стажировки

# (стажёр, подразделение, наставник, сценарий)
INTERNS = [
    ("Кузнецов Илья", "Разработка", "Орлов П.", "перегруз"),
    ("Соколова Дарья", "Аналитика", "Белов А.", "нет наставника"),
    ("Морозов Артём", "Клиентский сервис", "Зайцева О.", "мало задач"),
    ("Волкова Анна", "Финансы", "Титова Е.", "молчит"),
    ("Лебедев Никита", "Эксплуатация сети", "Громов С.", "плохой месяц"),
    ("Новикова Полина", "Разработка", "Орлов П.", "вежливые оценки"),
    ("Егоров Максим", "Эксплуатация сети", "Громов С.", "наставник недоволен"),
    ("Павлова Вера", "Аналитика", "Белов А.", "занятой наставник"),
    ("Фёдоров Глеб", "Аналитика", "Белов А.", "занятой наставник"),
    ("Смирнов Олег", "Разработка", "Орлов П.", None),
    ("Иванова Мария", "Разработка", "Крылова Н.", None),
    ("Попов Денис", "Разработка", "Крылова Н.", None),
    ("Васильева Юлия", "Аналитика", "Мельник Р.", None),
    ("Петров Кирилл", "Аналитика", "Мельник Р.", None),
    ("Михайлова Алиса", "Клиентский сервис", "Зайцева О.", None),
    ("Семёнов Тимур", "Клиентский сервис", "Зайцева О.", None),
    ("Голубева Ксения", "Клиентский сервис", "Жуков В.", None),
    ("Виноградов Лев", "Финансы", "Титова Е.", None),
    ("Богданова Софья", "Финансы", "Титова Е.", None),
    ("Воробьёв Роман", "Финансы", "Жуков В.", None),
    ("Тарасова Ева", "Эксплуатация сети", "Громов С.", None),
    ("Белоусов Марк", "Эксплуатация сети", "Сафонов Д.", None),
    ("Комарова Лиза", "Эксплуатация сети", "Сафонов Д.", None),
    ("Никитин Егор", "Эксплуатация сети", "Сафонов Д.", None),
]

GOOD = [
    "Дали интересную задачу, разобрался сам",
    "Наставник подробно объяснил процесс",
    "Познакомился с командой, все помогают",
    "Впервые выкатил свою задачу в работу",
    "Понравились внутренние митапы",
    "Научился работать с новой системой",
    "Хорошая атмосфера в отделе",
    "Получил полезную обратную связь по задаче",
]
BAD_MILD = ["", "", "", "Нет", "Всё нормально", "Долго выдавали доступы", "Хотелось бы больше обратной связи", ""]
MENTOR_OK = [
    "Работает хорошо, вопросы задаёт по делу",
    "Быстро учится, замечания учитывает",
    "Справляется с задачами, стал самостоятельнее",
    "Хороший прогресс за месяц",
    "Аккуратно выполняет задачи, вовремя",
    "",
]

S_AVG = ["s_tasks", "s_load", "s_mentor", "s_growth", "s_team", "s_overall"]
M_AVG = ["m_quality", "m_indep", "m_engage", "m_progress", "m_team"]


def clip(x, lo=1, hi=5):
    return max(lo, min(hi, int(round(x))))


def normal_month(base):
    s = {q: clip(base + random.gauss(0, 0.45)) for q in S_AVG}
    s["s_stay"] = clip(base + random.gauss(0, 0.5))
    s["s_nps"] = clip(base * 2 + random.gauss(0, 0.8), 0, 10)
    s["s_good"] = random.choice(GOOD)
    s["s_bad"] = random.choice(BAD_MILD)
    m = {q: clip(base + random.gauss(0, 0.45)) for q in M_AVG}
    m["m_hire"] = clip(base + random.gauss(0, 0.4))
    m["m_time"] = clip(4 + random.gauss(0, 0.6))
    m["m_comment"] = random.choice(MENTOR_OK)
    return s, m


def by_month(values, month):
    return values[month - 1]


def apply_scenario(name, month, s, m):
    # возвращает False, если стажёр в этом месяце анкету не заполнил
    if name == "перегруз":
        s["s_load"] = by_month([4, 4, 3, 2, 1], month)
        s["s_overall"] = by_month([5, 4, 4, 3, 2], month)
        s["s_stay"] = by_month([5, 4, 4, 3, 2], month)
        s["s_nps"] = by_month([9, 8, 7, 5, 3], month)
        s["s_bad"] = by_month([
            "", "",
            "Задач стало заметно больше, иногда не успеваю",
            "Постоянно сижу до ночи, совмещать с учёбой очень тяжело",
            "Работаю по выходным, сил уже нет. Не уверен, что дотяну до конца стажировки",
        ], month)
        for q in M_AVG:
            m[q] = 5
        m["m_comment"] = "Отлично справляется, берёт много задач"

    elif name == "нет наставника":
        s["s_mentor"] = by_month([4, 3, 2, 2, 1], month)
        s["s_tasks"] = by_month([4, 3, 3, 2, 2], month)
        s["s_overall"] = by_month([4, 4, 3, 3, 2], month)
        s["s_nps"] = by_month([8, 7, 6, 5, 4], month)
        s["s_bad"] = by_month([
            "", "Наставник часто занят",
            "Наставник почти не отвечает, вопросы висят по несколько дней",
            "Не понимаю, к кому идти с вопросами",
            "Наставника практически не вижу, задачи беру наугад",
        ], month)
        m["m_time"] = by_month([3, 2, 2, 1, 1], month)
        for q in M_AVG:
            m[q] = clip(3 + random.gauss(0, 0.3))
        m["m_comment"] = by_month([
            "", "", "Мало времени на стажёра, много своих задач",
            "Не успеваю проверять работу стажёра", "Времени на наставничество нет совсем",
        ], month)

    elif name == "занятой наставник":
        s["s_mentor"] = clip(3 + random.gauss(0, 0.4))
        m["m_time"] = by_month([3, 2, 2, 2, 1], month)

    elif name == "мало задач":
        s["s_growth"] = by_month([4, 3, 2, 2, 2], month)
        s["s_tasks"] = by_month([3, 3, 2, 2, 2], month)
        s["s_overall"] = by_month([4, 3, 3, 3, 2], month)
        s["s_load"] = 5
        s["s_stay"] = by_month([4, 3, 3, 2, 2], month)
        s["s_bad"] = by_month([
            "", "Хотелось бы больше задач",
            "Задач мало, в основном мелкие поручения",
            "Целыми днями нечего делать",
            "Нечего делать, ничему не учусь",
        ], month)

    elif name == "молчит":
        if month == 5:
            m["m_engage"] = 2
            m["m_comment"] = "Стала реже появляться, на сообщения отвечает с задержкой"
            return False
        for q in S_AVG:
            s[q] = clip(by_month([4.2, 3.8, 3.2, 2.8, 0], month) + random.gauss(0, 0.3))
        s["s_bad"] = by_month(["", "", "Не очень понимаю, зачем мои задачи", "", ""], month)

    elif name == "плохой месяц":
        if month == 5:
            s["s_overall"], s["s_load"], s["s_growth"] = 2, 2, 3
            s["s_bad"] = "Сессия, было сложно совмещать, но это временно"

    elif name == "вежливые оценки":
        for q in S_AVG:
            s[q] = random.choice([4, 5])
        s["s_stay"], s["s_nps"] = 4, 8
        s["s_bad"] = by_month([
            "", "", "",
            "Зарплата стажёра небольшая, смотрю другие варианты",
            "Получила оффер в другой компании, думаю уходить",
        ], month)

    elif name == "наставник недоволен":
        m["m_quality"] = by_month([4, 3, 2, 2, 2], month)
        m["m_indep"] = by_month([3, 3, 2, 2, 2], month)
        m["m_progress"] = by_month([4, 3, 3, 2, 2], month)
        m["m_engage"] = by_month([4, 3, 3, 3, 2], month)
        m["m_hire"] = by_month([4, 3, 3, 2, 2], month)
        m["m_comment"] = by_month([
            "", "Нужно внимательнее относиться к деталям",
            "Часто ошибается в простых вещах, приходится переделывать",
            "Замечания не учитывает, ошибки повторяются",
            "Прогресса нет, работу приходится переделывать",
        ], month)
    return True


def records():
    # одна запись = один стажёр в одном месяце: шапка, ответы стажёра, ответы наставника, заполнил ли стажёр анкету
    random.seed(7)
    out = []
    for name, dept, mentor, scenario in INTERNS:
        base = random.uniform(3.9, 4.7)
        for month in range(1, MONTHS + 1):
            s, m = normal_month(base)
            answered = apply_scenario(scenario, month, s, m)
            ts = f"2026-{5 + month:02d}-{random.randint(25, 28)} {random.randint(10, 18)}:{random.randint(10, 59)}"
            out.append(([ts, name, dept, mentor, month], s, m, answered))
    return out


def main():
    q = {}
    with open(QUESTIONS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            q[row["id"]] = row
    meta = [q[i]["column"] for i in ["ts", "intern", "dept", "mentor", "month"]]
    s_ids = [i for i, r in q.items() if r["role"] == "intern"]
    m_ids = [i for i, r in q.items() if r["role"] == "mentor"]

    s_rows, m_rows = [], []
    for head, s, m, answered in records():
        if answered:
            s_rows.append(head + [s[i] for i in s_ids])
        m_rows.append(head + [m[i] for i in m_ids])

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    for fname, ids, rows in [("otvety_stazhery.csv", s_ids, s_rows), ("otvety_nastavniki.csv", m_ids, m_rows)]:
        with open(DEMO_DIR / fname, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(meta + [q[i]["column"] for i in ids])
            w.writerows(rows)
        print(fname, len(rows), "строк")


if __name__ == "__main__":
    main()
