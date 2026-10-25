@echo off
chcp 65001 >nul
cd /d "%~dp0"
title GESTSCO - Systeme de Gestion Scolaire
where py >nul 2>nul
if %errorlevel%==0 (
    set PYTHON=py -3
) else (
    set PYTHON=python
)
rem --- Camera (module Carte) : OpenCV est installe automatiquement une seule fois, si internet est disponible.
%PYTHON% -c "import cv2" >nul 2>nul
if errorlevel 1 (
    if not exist "%LOCALAPPDATA%\GESTSCO\opencv_essaye.txt" (
        echo Installation de la camera ^(OpenCV^), une seule fois. Patientez...
        %PYTHON% -m pip install opencv-python
        if not exist "%LOCALAPPDATA%\GESTSCO" mkdir "%LOCALAPPDATA%\GESTSCO"
        echo essaye> "%LOCALAPPDATA%\GESTSCO\opencv_essaye.txt"
    )
)
%PYTHON% main.py
if errorlevel 1 (
    echo.
    echo Une erreur s'est produite. Verifiez que Python est bien installe.
    echo Envoyez-moi le message affiche ci-dessus.
    pause
)
