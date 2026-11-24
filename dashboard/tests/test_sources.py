# Проверяем два способа получать ответы автоматически: по ссылке на CSV и через webhook.
import http.server
import os
import sys
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, ingest, metrics  # noqa: E402
from core.config import DEMO_DIR  # noqa: E402


def test_csv_by_link(tmp_path):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = db.connect(tmp_path / "t.db")
        url = f"http://127.0.0.1:{server.server_port}/otvety_stazhery.csv"
        res = ingest.ingest(conn, url, "intern")
        assert res["анкет"] == 119 and not res["нераспознанные колонки"]
    finally:
        server.shutdown()


def test_webhook(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "w.db")
    os.environ["WEBHOOK_TOKEN"] = "secret"
    sys.modules.pop("webhook", None)
    from fastapi.testclient import TestClient

    import webhook

    webhook.LOG = tmp_path / "log.jsonl"  # журнал теста не должен попадать в настоящий
    client = TestClient(webhook.app)
    body = {
        "ФИО стажёра": "Тестов Тест", "Подразделение": "Аналитика", "Наставник": "Белов А.",
        "Месяц стажировки": 2, "Нагрузка мне по силам": 2,
        "Что мешало или что хочется изменить?": "Сижу до ночи, не успеваю",
        "Лишний вопрос": "да",
    }
    assert client.post("/answer/intern", json=body).status_code == 403
    r = client.post("/answer/intern", json=body, headers={"x-token": "secret"})
    assert r.status_code == 200 and r.json() == {"saved": 2, "unknown": ["Лишний вопрос"]}
    # тот же ответ второй раз не должен задвоиться
    client.post("/answer/intern", json=body, headers={"x-token": "secret"})
    a = metrics.load(webhook.conn)
    assert len(a) == 2
    com = metrics.comments(webhook.conn, a)
    assert com["signals"].iloc[0] == ["перегруз"]


def test_webhook_understands_different_shapes():
    import webhook
    flat = {"ФИО стажёра": "А Б", "Месяц стажировки": "2"}
    assert webhook.flatten(flat) == flat
    listed = [{"question": {"label": "ФИО стажёра"}, "value": "А Б"}, {"label": "Месяц стажировки", "value": ["2"]}]
    assert webhook.flatten(listed) == {"ФИО стажёра": "А Б", "Месяц стажировки": "2"}
    nested = {"id": 5, "answers": {"q1": {"question": {"label": "ФИО стажёра"}, "value": "А Б"}}}
    assert webhook.flatten(nested)["ФИО стажёра"] == "А Б"
    assert webhook.flatten('{"ФИО стажёра": "А Б"}') == {"ФИО стажёра": "А Б"}
