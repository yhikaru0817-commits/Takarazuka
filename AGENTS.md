# AGENTS.md（Codex / Claude などのAIエージェント向け）

## 個人情報の扱い（最優先）
- このリポジトリで扱う実データにはファンの個人情報（氏名・住所・電話・メール）が含まれる。
- `data/` と `output/`、`*.xlsx` `*.csv` は `.gitignore` 済み。**絶対にコミット・送信しない。**
  `.gitignore` のこれらの行を削除しないこと。
- 実データの内容をログ・コンソール・コード・コメント・コミットメッセージに書かない。
- 実データを外部APIやWebサービスに送らない。処理はローカルで完結させる。
- テストは架空データのみを使う（`tests/test_pipeline.py` を参照）。

## 構成
- `takarazuka_data/standardize.py` : 既存シートの整形（`python -m takarazuka_data.standardize`）。**このリポジトリの主な役割。**
- 整形後のデータの仕様は `DATA_SPEC.md`（顧客マスターは別の人が作る。`python -m takarazuka_data` の名寄せ・顧客番号は参考実装）。

## テスト
```bash
python3 -m unittest discover -s tests -t .
```
