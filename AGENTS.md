# AGENTS.md（Codex / Claude などのAIエージェント向け）

## 個人情報の扱い（最優先）
- このリポジトリで扱う実データにはファンの個人情報（氏名・住所・電話・メール）が含まれる。
- `data/` と `output/`、`*.xlsx` `*.csv` は `.gitignore` 済み。**絶対にコミット・送信しない。**
  `.gitignore` のこれらの行を削除しないこと。
- 実データの内容をログ・コンソール・コード・コメント・コミットメッセージに書かない。
- 実データを外部APIやWebサービスに送らない。処理はローカルで完結させる。
- テストは架空データのみを使う（`tests/test_pipeline.py` を参照）。

## 構成
- `takarazuka_data/` : データ整形（`python -m takarazuka_data`）
- 出力の仕様は `DATA_SPEC.md`。配分システムは `person_id` をキーに出力CSVを読む。

## テスト
```bash
python3 -m unittest discover -s tests -t .
```
