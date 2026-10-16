@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запускаю панель управления твич-ботом...
echo Панель откроется в браузере. Это окно можно свернуть.
"%~dp0venv\Scripts\python.exe" "%~dp0panel.py"
pause
