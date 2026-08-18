@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 凤仪天下 - 后端服务
echo ========================================
echo   凤仪天下 后端服务启动中...
echo ========================================
cd /d "%~dp0"
if exist venv\Scripts\activate.bat call venv\Scripts\activate
python app.py
pause