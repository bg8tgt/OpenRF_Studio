@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=D:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe
start "" "%PY%" "run.py"
