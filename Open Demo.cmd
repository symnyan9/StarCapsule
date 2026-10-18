@echo off
setlocal
python "%~dp0run.py" demo --output "%~dp0exports\review-demo.html" --force
if errorlevel 1 exit /b 1
start "" "%~dp0exports\review-demo.html"
