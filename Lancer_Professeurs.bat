@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GESTSCO - Saisie des points (serveur)
where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py -3
) else (
    set PYTHON=python
)
%PYTHON% serveur_notes.py
pause
