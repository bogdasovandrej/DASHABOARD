# Быстрая проверка, что нейросеть подключена и отвечает в нужном формате.
# Запуск: python scripts/check_llm.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import comments, llm

TESTS = [
    {"role": "intern", "text": "Получила оффер в другой компании, думаю уходить"},
    {"role": "intern", "text": "Сессия, было сложно совмещать, но это временно"},
    {"role": "mentor", "text": "Времени на наставничество нет совсем"},
    {"role": "intern", "text": "Всё отлично, дали интересную задачу"},
]

if not llm.name():
    sys.exit("Нейросеть не настроена. Скопируйте .env.example в .env и впишите ключ.")

print("Модель:", llm.name())
result = comments.by_llm(TESTS)
for i, t in enumerate(TESTS, 1):
    print(f"\n{t['text']}\n  ->", result.get(i, "НЕТ ОТВЕТА"))
if len(result) < len(TESTS):
    print("\nЧасть комментариев модель не разобрала. В дашборде для них сработает словарь.")
