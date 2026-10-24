@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import pandas, openpyxl" 2>nul || %PY% -m pip install -r requirements.txt
echo === 1. 既存シートの整形 (data/original → data/raw) ===
%PY% -m takarazuka_data.standardize
echo.
echo === 2. 顧客マスター作成・統合 (data/raw → output) ===
%PY% -m takarazuka_data
if exist output start "" output
echo.
pause
