# НЕ ОТКРЫВАТЬ ДО КОНЦА ТРЕНИРОВКИ: здесь видно, какие проблемы заложены в данные.
# Делает файл trenirovka/otvety.xlsx с двумя листами. Запуск: python trenirovka/proverka/sdelat_dannye.py
import random
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "dashboard" / "scripts"))
sys.path.insert(0, str(HERE.parent.parent / "dashboard"))
from make_demo_data import by_month, clip, normal_month

MONTHS = 5
rnd = random.Random(5)

# (стажёр, блок, наставник, история)
INTERNS = [
    ("Гусева Алина", "ИТ-разработка", "Рябов К.", "ночами"),
    ("Захаров Пётр", "Аналитика данных", "Миронова Т.", "зовут в стартап"),
    ("Орлова Кира", "Абонентский сервис", "Фомин Г.", "наставник в разъездах"),
    ("Тихонов Марк", "Сеть доступа", "Лаптев В.", "пропал"),
    ("Давыдова Яна", "Финансы и закупки", "Суханова Л.", "наставник недоволен"),
    ("Комаров Денис", "Умные решения", "Абрамов И.", "перекладывает файлы"),
    ("Белова Ника", "ИТ-разработка", "Рябов К.", "болела"),
    ("Жданов Олег", "Сеть доступа", "Лаптев В.", "отписки"),
    ("Соловьёва Эля", "Абонентский сервис", "Фомин Г.", "конфликт"),
    ("Маслов Игорь", "Абонентский сервис", "Фомин Г.", "занятой наставник"),
    ("Ершова Тая", "ИТ-разработка", "Рябов К.", None),
    ("Котов Савва", "ИТ-разработка", "Власова Д.", None),
    ("Панова Злата", "ИТ-разработка", "Власова Д.", None),
    ("Рогов Тимофей", "Аналитика данных", "Миронова Т.", None),
    ("Шилова Майя", "Аналитика данных", "Миронова Т.", None),
    ("Носков Арсений", "Аналитика данных", "Юдин С.", None),
    ("Блинова Вика", "Аналитика данных", "Юдин С.", None),
    ("Гришин Матвей", "Абонентский сервис", "Карпова Ж.", None),
    ("Зуева Ульяна", "Абонентский сервис", "Карпова Ж.", None),
    ("Мухин Ян", "Сеть доступа", "Лаптев В.", None),
    ("Савина Рита", "Сеть доступа", "Быков Н.", None),
    ("Третьяков Лука", "Сеть доступа", "Быков Н.", None),
    ("Фролова Нина", "Сеть доступа", "Быков Н.", None),
    ("Кулагин Фёдор", "Финансы и закупки", "Суханова Л.", None),
    ("Лыткина Аня", "Финансы и закупки", "Суханова Л.", None),
    ("Аксёнов Герман", "Финансы и закупки", "Ильин Р.", None),
    ("Дроздова Мила", "Умные решения", "Абрамов И.", None),
    ("Уваров Клим", "Умные решения", "Абрамов И.", None),
    ("Чернова Лада", "Умные решения", "Ильин Р.", None),
    ("Щукин Родион", "Умные решения", "Ильин Р.", None),
]


def story(name, month, s, m):
    # возвращает False, если стажёр анкету не заполнил
    if name == "ночами":
        s["s_load"] = by_month([4, 3, 2, 1, 1], month)
        s["s_overall"] = by_month([5, 4, 3, 3, 2], month)
        s["s_stay"] = by_month([5, 4, 4, 3, 2], month)
        s["s_nps"] = by_month([9, 8, 6, 5, 4], month)
        s["s_bad"] = by_month(["", "", "Объём работы вырос", "Задач столько, что сижу ночами. Учёбу почти забросила",
                               "Сплю по четыре часа, на пары не хожу"], month)
        for q in ["m_quality", "m_indep", "m_engage", "m_progress", "m_team"]:
            m[q] = 5
        m["m_comment"] = "Лучший стажёр в отделе, закрывает задачи быстрее штатных"

    elif name == "зовут в стартап":
        for q in ["s_tasks", "s_load", "s_mentor", "s_growth", "s_team", "s_overall"]:
            s[q] = rnd.choice([4, 5])
        s["s_stay"], s["s_nps"] = 4, 9
        s["s_bad"] = by_month(["", "", "", "Друзья зовут к себе в стартап, условия там интереснее",
                               "Рассматриваю предложение от другого работодателя"], month)

    elif name == "наставник в разъездах":
        s["s_mentor"] = by_month([4, 2, 2, 1, 1], month)
        s["s_tasks"] = by_month([4, 3, 2, 2, 2], month)
        s["s_overall"] = by_month([4, 3, 3, 2, 2], month)
        s["s_nps"] = by_month([8, 6, 5, 4, 4], month)
        s["s_bad"] = by_month(["", "Наставник в командировках", "Вопросы задаю в общий чат и жду по два дня",
                               "К наставнику не пробиться", "Работаю вслепую, проверять мою работу некому"], month)
        m["m_time"] = by_month([2, 2, 1, 1, 1], month)
        m["m_comment"] = by_month(["", "Часто в разъездах", "", "Физически не успеваю заниматься стажёрами", ""], month)

    elif name == "занятой наставник":
        s["s_mentor"] = clip(3 + rnd.gauss(0, 0.4))
        m["m_time"] = by_month([2, 2, 1, 1, 1], month)

    elif name == "пропал":
        if month >= 4:
            m["m_engage"] = 2
            m["m_comment"] = by_month(["", "", "", "Стал пропускать планёрки",
                                       "На планёрках не появляется, задачи сдаёт с опозданием"], month)
            return False
        for q in ["s_tasks", "s_load", "s_mentor", "s_growth", "s_team", "s_overall"]:
            s[q] = clip(by_month([4.3, 3.6, 3.0], month) + rnd.gauss(0, 0.3))
        s["s_bad"] = by_month(["", "Ожидал другого", ""], month)

    elif name == "наставник недоволен":
        m["m_quality"] = by_month([4, 3, 2, 2, 2], month)
        m["m_indep"] = by_month([3, 3, 2, 2, 1], month)
        m["m_progress"] = by_month([4, 3, 3, 2, 2], month)
        m["m_hire"] = by_month([4, 3, 3, 2, 2], month)
        m["m_comment"] = by_month(["", "", "В отчётах постоянно расхождения, сверяю всё заново",
                                   "Одни и те же недочёты из месяца в месяц", "Роста не вижу"], month)

    elif name == "перекладывает файлы":
        s["s_growth"] = by_month([4, 3, 2, 2, 1], month)
        s["s_tasks"] = by_month([4, 3, 3, 2, 2], month)
        s["s_overall"] = by_month([4, 4, 3, 3, 2], month)
        s["s_stay"] = by_month([4, 3, 3, 2, 2], month)
        s["s_load"] = 5
        s["s_bad"] = by_month(["", "", "Хочется настоящих задач", "Перекладываю файлы из папки в папку",
                               "Не понимаю, зачем я здесь"], month)

    elif name == "болела":
        if month == 5:
            s["s_overall"], s["s_load"], s["s_growth"] = 2, 2, 3
            s["s_bad"] = "Болела две недели, выпала из процесса, сейчас навёрстываю"

    elif name == "отписки":
        if month >= 3:
            for q in ["s_tasks", "s_load", "s_mentor", "s_growth", "s_team", "s_overall", "s_stay"]:
                s[q] = 5
            s["s_nps"] = 10
            s["s_good"] = s["s_bad"] = ""
        m["m_engage"] = by_month([4, 4, 3, 2, 2], month)
        m["m_progress"] = by_month([4, 4, 3, 3, 2], month)
        m["m_quality"] = by_month([4, 4, 3, 3, 3], month)
        m["m_comment"] = by_month(["", "", "", "Делает ровно то, что сказано", "Работает строго по инструкции, инициативы ноль"], month)

    elif name == "конфликт":
        s["s_team"] = by_month([4, 3, 2, 1, 1], month)
        s["s_overall"] = by_month([4, 4, 3, 2, 2], month)
        s["s_bad"] = by_month(["", "", "В команде есть напряжение", "Старший коллега при всех высмеивает мои ошибки",
                               "Не хочу приходить в офис из-за одного человека"], month)
    return True


def seven(x):
    return {1: 1, 2: rnd.choice([2, 3]), 3: 4, 4: rnd.choice([5, 6]), 5: 7}[x]


def ten(x):
    return max(1, 2 * x - rnd.randint(0, 1))


def messy(name):
    r = rnd.random()
    if r < 0.04:
        return name.upper()
    if r < 0.08:
        return " " + name.replace(" ", "  ")
    return name


def main():
    random.seed(23)
    s_rows, m_rows = [], []
    for n, (name, block, mentor, scenario) in enumerate(INTERNS, 1):
        base = random.uniform(3.9, 4.7)
        for month in range(1, MONTHS + 1):
            s, m = normal_month(base)
            answered = story(scenario, month, s, m)
            ts = f"{rnd.randint(24, 28)}.{5 + month:02d}.2026 {rnd.randint(9, 19)}:{rnd.randint(10, 59)}"
            if answered:
                s_rows.append({
                    "Отметка времени": ts, "Email": f"stazher{n:02d}@example.com", "ФИО": messy(name), "Блок": block,
                    "Наставник": mentor, "Месяц программы": f"{month}-й", "Согласие на обработку данных": "Да",
                    "Мне ясно, чего от меня ждут": seven(s["s_tasks"]),
                    "Я часто перерабатываю": 8 - seven(s["s_load"]),
                    "Наставник давал обратную связь в этом месяце": "Да" if s["s_mentor"] >= 3 else "Нет",
                    "Могу обратиться к наставнику, когда нужна помощь": seven(s["s_mentor"]),
                    "Задачи кажутся мне бессмысленными": 8 - seven(s["s_growth"]),
                    "Мне комфортно в коллективе": seven(s["s_team"]),
                    "Доволен(на) стажировкой в целом": seven(s["s_overall"]),
                    "Вижу себя в компании через год": seven(s["s_stay"]),
                    "Порекомендую стажировку друзьям (0–10)": s["s_nps"],
                    "Что понравилось": s["s_good"],
                    "Что бы вы изменили": "" if s["s_bad"] in ("Нет", "Всё нормально") else s["s_bad"],
                })
            m_rows.append({
                "Отметка времени": ts, "ФИО наставника": mentor, "Стажёр (ФИО)": messy(name), "Блок": block,
                "Месяц программы": f"{month}-й",
                "Оценка качества работы": ten(m["m_quality"]),
                "Приходится переделывать работу за стажёром": 11 - ten(m["m_indep"]),
                "Вовлечённость": ten(m["m_engage"]),
                "Рост за месяц": ten(m["m_progress"]),
                "Взял(а) бы в свою команду на постоянную работу": ten(m["m_hire"]),
                "Успеваю уделять стажёру время": ten(m["m_time"]),
                "Комментарий": m["m_comment"],
            })

    def dirty(rows):
        rows = rows + rnd.sample(rows, 4)          # четыре анкеты отправлены дважды
        rnd.shuffle(rows)
        df = pd.DataFrame(rows)
        empty = pd.DataFrame([{c: None for c in df.columns}] * 2)  # и две пустые строки
        return pd.concat([df.iloc[:40], empty, df.iloc[40:]], ignore_index=True)

    out = HERE.parent / "otvety.xlsx"
    with pd.ExcelWriter(out) as w:
        dirty(s_rows).to_excel(w, sheet_name="Стажёры", index=False)
        dirty(m_rows).to_excel(w, sheet_name="Наставники", index=False)
    print(out.name, "стажёры:", len(s_rows), "наставники:", len(m_rows))


if __name__ == "__main__":
    main()
