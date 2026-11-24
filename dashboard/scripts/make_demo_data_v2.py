# Второй тренировочный набор. Истории стажёров те же, что в первом, но всё остальное другое,
# как может быть на финале: другие названия вопросов, шкала 1-10, обратные вопросы, один комментарий
# вместо двух, Excel вместо CSV, "3 месяц" вместо 3, дубли строк и ФИО в разном написании.
# Анкета для него описана в survey/questions_v2.csv.
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import ROOT
from make_demo_data import records

OUT = ROOT / "data" / "demo_v2"
rnd = random.Random(11)


def ten(x):
    return max(1, 2 * x - rnd.randint(0, 1))  # 5 -> 9 или 10, 1 -> 1 или 2


def messy(name):
    r = rnd.random()
    if r < 0.03:
        return name.lower()
    if r < 0.06:
        return "  " + name.replace(" ", "   ").upper()
    return name


def main():
    s_rows, m_rows = [], []
    for (ts, name, dept, mentor, month), s, m, answered in records():
        head = {"Отдел": dept, "Куратор": mentor, "Номер месяца": f"{month} месяц", "Дата заполнения": ts}
        if answered:
            comment = s["s_bad"] if s["s_bad"] not in ("", "Нет", "Всё нормально") else s["s_good"]
            s_rows.append({
                "Ваш комментарий": comment,
                "Сотрудник (ФИО)": messy(name), **head,
                "Понимаю, какие задачи передо мной стоят": ten(s["s_tasks"]),
                "Нагрузка слишком высокая": 11 - ten(s["s_load"]),
                "Мне приходится подолгу ждать ответа куратора": 11 - ten(s["s_mentor"]),
                "Получаю новые знания и навыки": ten(s["s_growth"]),
                "Общая удовлетворённость стажировкой": ten(s["s_overall"]),
                "Планирую остаться в компании": ten(s["s_stay"]),
                "Готовность рекомендовать стажировку (0-10)": s["s_nps"],
            })
        m_rows.append({
            "Сотрудник (ФИО)": messy(name), **head,
            "Качество выполнения задач": m["m_quality"],
            "Стажёру часто требуется помощь в простых задачах": 6 - m["m_indep"],
            "Проявляет инициативу": m["m_engage"],
            "Динамика за месяц": m["m_progress"],
            "Рекомендую к переходу в штат": m["m_hire"],
            "У меня достаточно времени на стажёра": m["m_time"],
            "Комментарий куратора": m["m_comment"],
        })

    OUT.mkdir(parents=True, exist_ok=True)
    for fname, rows in [("otvety_stazhery.xlsx", s_rows), ("otvety_nastavniki.xlsx", m_rows)]:
        rows = rows + rnd.sample(rows, 3)  # три анкеты отправлены дважды
        pd.DataFrame(rows).to_excel(OUT / fname, index=False)
        print(fname, len(rows), "строк")


if __name__ == "__main__":
    main()
