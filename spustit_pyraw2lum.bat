@echo off
cd /d "%~dp0"
python -m raw2lum
if errorlevel 1 pause
