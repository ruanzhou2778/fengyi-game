@echo off
title 凤仪天下 - 后端服务
echo ========================================
echo   🌸 凤仪天下 后端服务启动中...
echo ========================================
cd /d "%~dp0"
call venv\Scripts\activate
python3 app.py
pause