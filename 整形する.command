#!/bin/bash
# ダブルクリックで実行（Mac）。既存シートの整形 → 顧客マスター作成・統合 を行い、output フォルダを開きます。
cd "$(dirname "$0")" || exit 1
python3 -c "import pandas, openpyxl" 2>/dev/null || python3 -m pip install --user -r requirements.txt
echo "=== 1. 既存シートの整形 (data/original → data/raw) ==="
python3 -m takarazuka_data.standardize
echo
echo "=== 2. 顧客マスター作成・統合 (data/raw → output) ==="
python3 -m takarazuka_data && open output
echo
read -n 1 -s -r -p "何かキーを押すと閉じます"
