@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [산림 큐레이터] 패키지 확인 중...
py -3 -m pip install -q -r requirements.txt
echo.
echo [산림 큐레이터] 서버 시작: http://localhost:8000  (종료하려면 이 창을 닫거나 Ctrl+C)
echo.
py -3 -m uvicorn main:app --port 8000 --reload
pause
