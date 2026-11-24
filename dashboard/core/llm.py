# Один вход для любой нейросети. Поддерживаются два варианта:
# 1) GigaChat (свой способ получения токена)
# 2) любой сервис с OpenAI-совместимым API: YandexGPT, MWS GPT, Ollama на своём компьютере и т.д.
# Что использовать, задаётся в файле .env. Если ничего не задано, дашборд работает на словаре.
import os
import time
import uuid

import requests

from . import config  # noqa: F401  (при импорте читает файл .env с ключами)

GIGA_OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# Сбер называет основным адрес https://api.giga.chat/v1, но 16.11.2026 он у нас не отвечал, а этот отвечал за секунду.
# Другой адрес можно задать в .env строкой GIGACHAT_URL=...
GIGA_API = "https://gigachat.devices.sberbank.ru/api/v1"
_token = {"value": None, "expires": 0}


def name():
    if os.getenv("GIGACHAT_KEY"):
        return os.getenv("GIGACHAT_MODEL", "GigaChat-2")
    if os.getenv("LLM_BASE_URL"):
        return os.getenv("LLM_MODEL", "модель не указана")
    return None


def _verify():
    # Сервера Сбера работают с сертификатом Минцифры, обычный Python ему не доверяет.
    # Правильно: скачать сертификат и указать путь в GIGACHAT_CA. Без него проверку отключаем.
    ca = os.getenv("GIGACHAT_CA")
    if ca:
        return ca
    requests.packages.urllib3.disable_warnings()
    return False


def _giga_token():
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    r = requests.post(
        GIGA_OAUTH,
        headers={
            "Authorization": f"Basic {os.getenv('GIGACHAT_KEY')}",
            "RqUID": str(uuid.uuid4()),
            "Accept": "application/json",
        },
        data={"scope": os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")},
        verify=_verify(),
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires"] = data["expires_at"] / 1000  # приходит в миллисекундах, живёт 30 минут
    return _token["value"]


def chat(system, user, temperature=0.1):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if os.getenv("GIGACHAT_KEY"):
        url = os.getenv("GIGACHAT_URL", GIGA_API).rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {_giga_token()}"}
        verify = _verify()
    else:
        url = os.getenv("LLM_BASE_URL").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'no-key')}"}
        verify = True
    r = requests.post(
        url,
        headers=headers,
        json={"model": name(), "messages": messages, "temperature": temperature},
        verify=verify,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
