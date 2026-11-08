@echo off
rem Double-click this file to start BotOffice.
rem It hands off to scripts\run.bat, which creates the virtual environment
rem and installs dependencies the first time.
title BotOffice
cd /d "%~dp0"
call "scripts\run.bat"
if errorlevel 1 pause
