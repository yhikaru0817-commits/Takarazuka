#!/bin/bash
# ダブルクリックで実行（Mac）。data/original のシートを、決められた形式に整形します。
# 結果は data フォルダに出ます（standardized_all.csv ほか）。
cd "$(dirname "$0")" || exit 1
python3 -c "import pandas, openpyxl" 2>/dev/null || python3 -m pip install --user -r requirements.txt
python3 -m takarazuka_data.standardize && open data
echo
read -n 1 -s -r -p "何かキーを押すと閉じます"
