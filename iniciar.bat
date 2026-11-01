@echo off
title Radar
cd /d "%~dp0"
py -c "import anthropic" 2>nul || py -m pip install --quiet -r requirements.txt
py server.py
pause
