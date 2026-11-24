# Эффект в рублях. Здесь только арифметика, все входные числа это допущения со страницы "Эффект".
# Настоящие значения знает только МГТС, поэтому в коде нет ни одной "зашитой" цифры компании.
import math

from .comments import BATCH, PROMPT

WEEKS = 4            # недель в месяце, для простоты
CHARS_PER_TOKEN = 3  # грубая оценка для русского текста
ANSWER_CHARS = 150   # примерный размер ответа нейросети на один комментарий


def loss_per_intern(pay, months, mentor_hours, mentor_rate, rehire):
    # Сколько компания теряет, если стажёр ушёл на таком-то месяце и не перешёл в штат
    parts = {
        "Выплаты стажёру": pay * months,
        "Время наставника": mentor_hours * WEEKS * months * mentor_rate,
        "Повторный набор": rehire,
    }
    return parts, sum(parts.values())


def ai_cost(n_comments, comment_chars, price_per_1000):
    # Стоимость разбора комментариев: промпт уходит один раз на пачку, плюс тексты, плюс ответы
    batches = math.ceil(n_comments / BATCH)
    chars = batches * len(PROMPT) + comment_chars + n_comments * ANSWER_CHARS
    return chars / CHARS_PER_TOKEN / 1000 * price_per_1000


def summary(loss, at_risk, keep_share, ai, server_month, months=6):
    kept = at_risk * keep_share
    saved = kept * loss
    cost = ai + server_month * months
    return {"kept": kept, "saved": saved, "cost": cost, "ratio": saved / cost if cost else None}
