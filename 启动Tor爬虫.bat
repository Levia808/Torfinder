@echo off
chcp 65001 >nul
title TORFINDER
cd /d "%~dp0"
echo 正在启动 TORFINDER...
where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%~dp0tor_relay_cli.py"
) else (
    python "%~dp0tor_relay_cli.py"
)
echo.
pause
