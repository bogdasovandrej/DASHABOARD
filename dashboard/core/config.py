import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "dashboard.db"))
QUESTIONS_CSV = ROOT / "survey" / "questions.csv"
DEMO_DIR = ROOT / "data" / "demo"
MGTS_QUESTIONS_CSV = ROOT / "survey" / "questions_mgts.csv"
MGTS_DEMO_DIR = ROOT / "data" / "mgts"


def questions_csv():
    # другую анкету подключаем так: QUESTIONS_CSV=survey/questions_v2.csv
    p = os.getenv("QUESTIONS_CSV")
    return ROOT / p if p else MGTS_QUESTIONS_CSV


def demo_dir():
    p = os.getenv("DEMO_DIR")
    return ROOT / p if p else MGTS_DEMO_DIR


# Пороги и баллы риска. Вынесены сюда, чтобы на финале менять их в одном месте.
LOW = 3.0            # средняя оценка месяца ниже этого: плохо
SO_SO = 3.5          # ниже этого: настораживает
DROP_BIG = 0.8       # падение к среднему за два прошлых месяца
DROP_SMALL = 0.5
GAP = 1.2            # расхождение между оценкой стажёра и наставника
FAST_SEC = 40        # анкета заполнена быстрее: скорее всего не читая
RED = 50             # с этого балла высокий риск
YELLOW = 25          # с этого балла средний

TOPICS = ["задачи", "нагрузка", "наставник", "команда", "развитие", "условия"]
SIGNALS = [
    "хочет уйти",
    "перегруз",
    "мало задач",
    "нет поддержки наставника",
    "конфликт",
    "потеря интереса",
    "слабые результаты",
]
