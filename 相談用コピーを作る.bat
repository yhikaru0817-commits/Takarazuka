@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
%PY% -c "import pandas, openpyxl" 2>nul || %PY% -m pip install -r requirements.txt
echo 個人情報を架空の値に置き換えたコピーを masked フォルダに作ります（data/original が元）
%PY% -m takarazuka_data.mask data/original -o masked
if exist masked start "" masked
echo.
pause
