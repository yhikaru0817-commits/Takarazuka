@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import pandas, openpyxl" 2>nul || %PY% -m pip install -r requirements.txt
%PY% -m takarazuka_data
if exist output start "" output
echo.
pause
