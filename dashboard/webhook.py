# Приёмник ответов по одной анкете. Яндекс Формы (интеграция «API» → «Запрос заданным методом»)
# после каждого заполнения шлют сюда POST с ответами. Дашборд и приёмник работают с одной базой,
# поэтому ответ сразу виден в дашборде.
# Запуск: uvicorn webhook:app --port 8000
# Адреса: /answer/intern для анкеты стажёра, /answer/mentor для анкеты наставника.
import json
import os
import time
from pathlib import Path

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from core import comments, db, ingest
from core.ingest import flatten_answer as flatten
from core.config import ROOT

app = FastAPI()
conn = db.connect()
LOG = Path(os.getenv("WEBHOOK_LOG_PATH") or ROOT / "data" / "webhook_log.jsonl")


def analyze():
    # разбор комментариев нейросетью может идти десятки секунд, а Яндекс ждёт ответа 5 секунд
    # и при задержке шлёт запрос повторно. Поэтому сначала отвечаем, потом разбираем.
    comments.run(db.connect())


@app.post("/answer/{role}")
async def answer(role: str, request: Request, tasks: BackgroundTasks):
    # простой пароль в заголовке, чтобы в базу не писал кто попало
    token = os.getenv("WEBHOOK_TOKEN")
    if token and request.headers.get("x-token") != token:
        raise HTTPException(403, "неверный токен")
    if role not in ("intern", "mentor"):
        raise HTTPException(404, "роль должна быть intern или mentor")
    raw = (await request.body()).decode("utf-8", errors="replace")
    # Сырой запрос пишем в журнал: по нему видно, что именно прислал сервис анкет. Файл только локальный.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "role": role, "body": raw[:20000]},
                           ensure_ascii=False) + "\n")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "тело запроса не JSON")
    row = flatten(body)
    try:
        rows, unknown = ingest.to_rows(pd.DataFrame([row]), role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        saved = ingest.save(conn, rows)
    except ValueError as e:
        raise HTTPException(409, str(e))
    if saved:
        tasks.add_task(analyze)
    return {"saved": saved, "unknown": unknown}


@app.get("/")
def alive():
    return {"ok": True}
