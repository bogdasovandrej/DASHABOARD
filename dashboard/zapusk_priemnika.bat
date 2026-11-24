@echo off
chcp 65001 >nul
rem Запускает приёмник ответов из Яндекс Форм и публичный туннель к нему.
rem VPN должен быть выключен: через него туннель не подключается.
cd /d "%~dp0"
start "Приёмник ответов" cmd /k python -m uvicorn webhook:app --host 127.0.0.1 --port 8000
timeout /t 3 >nul
echo.
echo Ниже появится адрес вида https://....trycloudflare.com
echo Его нужно вписать в обе формы: Интеграции - API - Адрес в интернете,
echo с окончанием /answer/intern для стажёра и /answer/mentor для наставника.
echo Адрес меняется при каждом запуске.
echo.
"%~dp0..\tunnel\cloudflared.exe" tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000
pause
