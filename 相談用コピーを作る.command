#!/bin/bash
# ダブルクリックで実行（Mac）。data/original の個人情報を架空の値に置き換えたコピーを masked に作ります。
cd "$(dirname "$0")" || exit 1
python3 -c "import pandas, openpyxl" 2>/dev/null || python3 -m pip install --user -r requirements.txt
python3 -m takarazuka_data.mask data/original -o masked && open masked
echo
read -n 1 -s -r -p "何かキーを押すと閉じます"
