#!/bin/bash
# ダブルクリックで実行（Mac）。data/raw のファイルを整形して output フォルダを開きます。
cd "$(dirname "$0")" || exit 1
python3 -c "import pandas, openpyxl" 2>/dev/null || python3 -m pip install --user -r requirements.txt
python3 -m takarazuka_data && open output
echo
read -n 1 -s -r -p "何かキーを押すと閉じます"
