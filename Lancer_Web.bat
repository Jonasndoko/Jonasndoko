@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GESTSCO - version web (essai sur cet ordinateur)
where py >nul 2>nul
if %errorlevel%==0 (set PYTHON=py -3) else (set PYTHON=python)
%PYTHON% -m pip install -r requirements.txt
echo.
echo Ouvrez http://127.0.0.1:5000 dans le navigateur.
set GESTISC_CODE_INSTALL=essai-local
%PYTHON% app_web.py
pause
