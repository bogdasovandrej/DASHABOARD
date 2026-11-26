# Тесты не должны ходить в настоящую нейросеть и в настоящую почту: это медленно, тратит токены и даёт разный ответ от запуска к запуску.
# Пустые значения выставляются до чтения .env, поэтому ключ из файла в тестах не используется.
import os

os.environ["GIGACHAT_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["YANDEX_MAIL"] = ""
os.environ["YANDEX_APP_PASSWORD"] = ""
os.environ.setdefault("QUESTIONS_CSV", "survey/questions.csv")
os.environ.setdefault("DEMO_DIR", "data/demo")
os.environ.setdefault("YANDEX_SUBJECT_INTERN", "[intern]")
os.environ.setdefault("YANDEX_SUBJECT_MENTOR", "[mentor]")
