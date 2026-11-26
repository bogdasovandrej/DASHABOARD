# Разбор текстовых комментариев.
# Основной путь: нейросеть возвращает по каждому комментарию тональность, темы и тревожные сигналы.
# Запасной путь: словарь ключевых слов. Он нужен, чтобы дашборд работал без интернета и без ключа.
import hashlib
import json
import re

from . import llm
from .config import SIGNALS, TOPICS

BATCH = 12

PROMPT = f"""Ты помогаешь HR-отделу разбирать комментарии из ежемесячных опросов стажёров и наставников.

На вход приходит JSON-список комментариев. У каждого есть id, автор (стажёр или наставник) и текст.
Для каждого комментария верни объект с полями:
- id: тот же, что на входе
- sentiment: число от -1 (очень плохо) до 1 (очень хорошо), 0 значит нейтрально
- topics: о чём комментарий, только из списка {TOPICS}
- signals: тревожные сигналы, только из списка {SIGNALS}. Если сигнала нет, пустой список
- quote: короткая дословная цитата из текста, которая подтверждает сигнал. Если сигналов нет, пустая строка

Правила:
1. Опирайся только на текст комментария, ничего не додумывай.
2. Вежливая формулировка не отменяет сигнал. "Смотрю другие варианты" это "хочет уйти".
3. Временная трудность (сессия, болезнь, отпуск) не сигнал, если человек сам пишет, что это временно.
4. Комментарий наставника описывает стажёра. Но если наставник пишет, что ему самому не хватает времени
   на стажёра, это сигнал "нет поддержки наставника".
5. Ответ: только JSON-список, без пояснений и без ```.

Пример входа:
[{{"id": 1, "author": "стажёр", "text": "Постоянно задерживаюсь после учёбы, не успеваю закрывать задачи в срок"}},
 {{"id": 2, "author": "стажёр", "text": "Была сессия, тяжело, но это временно"}},
 {{"id": 3, "author": "наставник", "text": "Быстро учится, но часто ошибается в расчётах"}}]
Пример ответа:
[{{"id": 1, "sentiment": -0.8, "topics": ["нагрузка"], "signals": ["перегруз"], "quote": "не успеваю закрывать задачи в срок"}},
 {{"id": 2, "sentiment": -0.2, "topics": ["нагрузка"], "signals": [], "quote": ""}},
 {{"id": 3, "sentiment": 0.1, "topics": ["развитие"], "signals": ["слабые результаты"], "quote": "часто ошибается в расчётах"}}]"""

SIGNAL_WORDS = {
    "хочет уйти": ["уходить", "уйти", "уволи", "оффер", "другие варианты", "другую компанию", "дотяну", "ищу работу",
                   "смотрю вакансии", "рассматриваю предложения", "не вижу смысла оставаться"],
    "перегруз": ["до ночи", "по выходным", "не успеваю", "перерабат", "сил уже нет", "сил нет", "выгор",
                 "зашиваюсь", "не тяну", "горят дедлайны", "задерживаюсь", "перегруз",
                 "высокая нагрузка", "слишком высокой", "снизить нагрузку", "нагрузка выше комфортной",
                 "много параллельных задач", "из-за нагрузки часть сроков"],
    "мало задач": ["нечего делать", "задач мало", "мало задач", "мелкие поручения", "без дела",
                   "простаиваю", "сижу без задач", "одна рутина"],
    "нет поддержки наставника": ["не отвечает", "вопросы висят", "к кому идти", "наставника практически не вижу",
                                 "наставника не вижу", "мало времени на стаж", "игнорит", "не выходит на связь",
                                 "нет обратной связи", "нет фидбека", "не хватает регулярной обратной связи",
                                 "не хватает регулярной связи", "редкая обратная связь", "обратной связи все еще недостаточно",
                                 "долго жду уточнений", "нужна более регулярная связь с наставником", "регулярных коротких встреч",
                                 "не успеваю проверять", "времени на наставничество нет", "наставник часто занят",
                                 "не хватает возможности быстро задать вопрос наставнику"],
    "конфликт": ["конфликт", "ссор", "грубо", "хамит", "давит", "токсичн"],
    "потеря интереса": ["ничему не учусь", "зачем мои задачи", "реже появляться", "с задержкой", "неинтересно",
                        "скучно", "потерял мотивацию", "нет мотивации"],
    "слабые результаты": ["ошибается", "переделывать из-за ошибок", "прогресса нет", "не учитывает", "ошибки повторяются",
                          "не справляется", "срывает сроки", "самостоятельность снизилась", "снизился темп"],
}
NO_ISSUES = [
    "сложностей за период не было", "серьезных сложностей нет", "критичных сложностей нет",
    "существенных сложностей нет", "существенных сложностей сейчас нет",
    "сложностей, требующих внимания, нет", "ничего не мешает", "ничего существенно не мешает",
    "существенных препятствий нет",
]
TOPIC_WORDS = {
    "задачи": ["задач", "поручен"],
    "нагрузка": ["нагруз", "не успеваю", "до ночи", "выходн", "совмещ", "сесси"],
    "наставник": ["наставни", "обратной связи", "обратную связь"],
    "команда": ["команд", "коллег", "отдел", "атмосфер"],
    "развитие": ["научил", "учусь", "учится", "митап", "разобрал", "прогресс"],
    "условия": ["зарплат", "доступ", "офис", "график", "оффер"],
}
POSITIVE = ["интересн", "понрав", "хорош", "отличн", "помога", "полезн", "научил", "справля", "быстро учится",
            "аккуратн", "объяснил", "самостоятельн", "вовремя"]
NEGATIVE = ["тяжело", "сложно", "не успеваю", "мало", "нечего", "не понимаю", "долго", "небольшая", "наугад",
            "внимательнее", "хотелось бы"]
TEMPORARY = ["временно", "сесси", "экзамен", "болел", "отпуск"]
EMPTY = {"", "нет", "все нормально", "все ок", "все хорошо", "ничего", "нет замечаний"}


def text_hash(role, text):
    return hashlib.sha1(f"{role}|{text}".encode()).hexdigest()


def simple(text):
    return re.sub(r"[^а-яa-z0-9 ]+", "", text.lower().replace("ё", "е")).strip()


def by_dictionary(text, role):
    t = text.lower().replace("ё", "е")
    if t.strip(" .!\n\t") in NO_ISSUES:
        return {"sentiment": 0.2, "topics": [], "signals": [], "quote": ""}
    matches = {signal: [word for word in words if word in t] for signal, words in SIGNAL_WORDS.items()}
    signals = [signal for signal, words in matches.items() if words]
    mentor_too_busy = any(phrase in t for phrase in (
        "не успеваю", "времени на наставничество нет", "мало времени на стаж",
    ))
    if role == "mentor" and "перегруз" in signals and mentor_too_busy:
        # "не успеваю" в комментарии наставника это его собственная занятость, а не перегруз стажёра
        signals.remove("перегруз")
        if "нет поддержки наставника" not in signals:
            signals.append("нет поддержки наставника")
    topics = [k for k, words in TOPIC_WORDS.items() if any(w in t for w in words)]
    pos = sum(w in t for w in POSITIVE)
    neg = sum(w in t for w in NEGATIVE)
    sentiment = -0.7 if signals else round((pos - neg) / max(1, pos + neg) * 0.6, 2)
    if not signals and sentiment < 0 and any(w in t for w in TEMPORARY):
        sentiment = -0.2  # то же правило, что в промпте: временная трудность не считается тревогой
    quote = ""
    if signals:
        # Сохраняем дословный отрезок от первого до последнего предложения с сигналом.
        triggers = [word for words in matches.values() for word in words]
        parts = [part for part in re.finditer(r"\S.*?(?:[.!?](?=\s|$)|\Z)", text, re.S)
                 if any(word in part[0].lower().replace("ё", "е") for word in triggers)]
        quote = text[parts[0].start():parts[-1].end()] if parts else text.strip()
    return {"sentiment": sentiment, "topics": topics, "signals": signals, "quote": quote}


def parse_answer(raw, batch):
    # Нейросеть может ошибиться в формате, поэтому всё проверяем:
    # значения только из наших списков, цитата обязана быть в исходном тексте.
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return {}
    texts = {i: item["text"] for i, item in enumerate(batch, 1)}
    out = {}
    for obj in data:
        if not isinstance(obj, dict) or obj.get("id") not in texts:
            continue
        try:
            sentiment = max(-1.0, min(1.0, float(obj.get("sentiment", 0))))
        except (TypeError, ValueError):
            sentiment = 0.0
        signals = [s for s in obj.get("signals") or [] if s in SIGNALS]
        quote = str(obj.get("quote") or "").strip()
        # Нет дословной цитаты — нет сигнала. Иначе на экране окажется тревога без доказательства.
        rejected = 0
        if not quote or quote not in texts[obj["id"]]:
            quote = ""
            rejected = len(signals)
            signals = []
        out[obj["id"]] = {
            "sentiment": sentiment,
            "topics": [t for t in obj.get("topics") or [] if t in TOPICS],
            "signals": signals,
            "quote": quote,
            "rejected": rejected,
        }
    return out


LETTER = "а-яёa-z"


def mask(text, names):
    # Фамилии и имена людей в нейросеть не отправляем. Меняем только целые слова:
    # иначе имя «Ева» портит слово «успеваю». Фамилию ловим с окончанием: «Белов», «Белову», «Беловым».
    # Сначала более длинные имена: это делает маскировку стабильной для текста и цитаты.
    for n in sorted(set(names), key=lambda value: (-len(value), value.casefold())):
        for part in n.replace(".", " ").split():
            if len(part) < 3:
                continue
            ending = f"[{LETTER}]*" if len(part) >= 4 else ""
            text = re.sub(f"(?<![{LETTER}]){re.escape(part)}{ending}(?![{LETTER}])", "[имя]", text, flags=re.I)
    return text


def by_llm(batch, names=()):
    sent = [{**item, "text": mask(item["text"], names)} for item in batch]
    payload = [
        {"id": i, "author": "стажёр" if item["role"] == "intern" else "наставник", "text": item["text"]}
        for i, item in enumerate(sent, 1)
    ]
    raw = llm.chat(PROMPT, json.dumps(payload, ensure_ascii=False))
    # цитату сверяем с тем текстом, который модель действительно видела
    return parse_answer(raw, sent)


def _short_hash(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]


# Версия разбора. Поменяли промпт, списки сигналов или словарь — версия меняется сама,
# и старые разборы пересчитываются при следующей загрузке.
PROMPT_VERSION = _short_hash([PROMPT, TOPICS, SIGNALS, SIGNAL_WORDS, NO_ISSUES,
                              "маскировка целых слов", "длинные имена первыми", "вторая попытка",
                              "сигнал подтверждается дословным правилом"])
DICT_VERSION = "словарь|" + _short_hash([SIGNAL_WORDS, NO_ISSUES, TOPIC_WORDS, POSITIVE, NEGATIVE, TEMPORARY, "цитата по всем сигналам"])


def target_version(use_llm=True):
    model = llm.name() if use_llm else None
    return f"{model}|{PROMPT_VERSION}" if model else DICT_VERSION


def checked_model_result(text, role, result):
    # Модель может пропустить явную жалобу или принять потребность стажёра в помощи
    # за нехватку времени самого наставника. Сигнал в светофоре оставляем только
    # при дословно проверяемом признаке; модель отвечает за тон и темы.
    rule = by_dictionary(text, role)
    result = dict(result)
    result["signals"] = rule["signals"]
    result["quote"] = rule["quote"] if rule["signals"] else ""
    return result


def pending(conn, version):
    # комментарии, которые ещё не разобраны или разобраны другой моделью, другим промптом или другим словарём
    rows = conn.execute("select distinct role, text from answers where text is not null").fetchall()
    done = {r[0] for r in conn.execute("select hash from comment_ai where version = ?", (version,))}
    return [{"role": r, "text": t, "hash": text_hash(r, t)} for r, t in rows if text_hash(r, t) not in done]


def run(conn, use_llm=True, progress=None):
    # Разбирает комментарии, которых ещё нет в таблице comment_ai. Возвращает статистику.
    version = target_version(use_llm)
    items = pending(conn, version)
    names = [r[0] for r in conn.execute("select distinct intern from answers")]
    names += [r[0] for r in conn.execute("select distinct mentor from answers")]
    stats = {"всего": len(items), "нейросеть": 0, "словарь": 0, "отклонено проверкой": 0, "ошибки": []}
    model = llm.name() if use_llm else None

    easy = [i for i in items if simple(i["text"]) in EMPTY]
    hard = [i for i in items if simple(i["text"]) not in EMPTY]
    for item in easy:
        # «нет», «всё нормально»: разбирать нечего, такой результат верен для любой модели
        _save(conn, item, {"sentiment": 0, "topics": [], "signals": [], "quote": ""}, "словарь", version)
        stats["словарь"] += 1

    for start in range(0, len(hard), BATCH):
        batch = hard[start:start + BATCH]
        answers = {}
        if model:
            try:
                answers = by_llm(batch, names)
            except Exception as e:  # сеть упала, ключ кончился и т.п. Тогда спасает словарь
                stats["ошибки"].append(str(e)[:200])
                model = None  # не ждём тот же сбой на каждой следующей пачке
        # Модель иногда находит сигнал, но не даёт дословную цитату, и проверка его выбрасывает.
        # Такой комментарий отправляем ещё раз отдельно: одна попытка, без цитаты сигнал так и не засчитается.
        for i in [i for i, r in answers.items() if r["rejected"]]:
            stats["повторно"] = stats.get("повторно", 0) + 1
            try:
                again = by_llm([batch[i - 1]], names).get(1)
            except Exception:
                again = None
            if again and again["signals"]:
                answers[i] = {**again, "rejected": 0}
        for i, item in enumerate(batch, 1):
            if i in answers:
                _save(conn, item, checked_model_result(item["text"], item["role"], answers[i]),
                      llm.name() + " + правила", version)
                stats["нейросеть"] += 1
                stats["отклонено проверкой"] += answers[i]["rejected"]
            else:
                # словарный разбор помечаем версией словаря: когда нейросеть заработает, комментарий разберётся заново
                _save(conn, item, by_dictionary(item["text"], item["role"]), "словарь", DICT_VERSION)
                stats["словарь"] += 1
        if progress:
            progress(min(1.0, (start + BATCH) / max(1, len(hard))))
    conn.commit()
    return stats


def _save(conn, item, r, source, version):
    conn.execute(
        "insert or replace into comment_ai (hash, sentiment, topics, signals, quote, source, version, rejected) "
        "values (?,?,?,?,?,?,?,?)",
        (item["hash"], r["sentiment"], json.dumps(r["topics"], ensure_ascii=False),
         json.dumps(r["signals"], ensure_ascii=False), r["quote"], source, version, r.get("rejected", 0)),
    )


SUMMARY_PROMPT = """Ты помогаешь HR-специалисту программы стажировок. Тебе дают факты об одном стажёре:
оценки по месяцам, причины, по которым система советует с ним поговорить, и цитаты из комментариев.
Напиши короткую сводку на русском, 3-4 предложения простым языком:
что происходит, насколько это серьёзно и что HR стоит сделать на этой неделе.
Используй только факты из входных данных. Не ставь диагнозов и не придумывай причин, которых нет в данных.
Имени стажёра в данных нет, пиши "стажёр"."""


def hr_summary(facts):
    # facts: текст с фактами без ФИО. Если нейросети нет, возвращает None, и дашборд покажет причины списком.
    if not llm.name():
        return None
    return llm.chat(SUMMARY_PROMPT, facts, temperature=0.3).strip()
