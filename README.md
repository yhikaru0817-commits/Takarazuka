# 宝塚ファンクラブ管理データ 整形ツール

チケット・お茶会/親睦会・グッズ・年間企画の各シートを読み込み、形式のばらつきを揃えて
「誰が・どのイベントで・いくら使ったか」を1つの形式にまとめます。

## 個人情報の取り扱い（重要）

- **すべてローカルPC上で処理します。** ネット通信は一切行いません。
- 実データは `data/raw/` に、出力は `output/` に置きます。どちらも `.gitignore` 済みで、
  `*.xlsx` / `*.csv` もリポジトリには入らない設定です。**実データを GitHub に上げないでください。**
- 画面には件数だけを表示し、氏名などは出しません。
- 人物ID（`P` + 英数字）はハッシュ値なので、IDから個人情報は分かりません。
- テストは架空データのみを使っています。

## 使い方

```bash
pip install -r requirements.txt
# data/raw/ に Excel (.xlsx) または CSV を置く（1ファイルに複数シート可）
python -m takarazuka_data            # 既定: data/raw → output
python -m takarazuka_data 入力フォルダ -o 出力フォルダ
```

Google スプレッドシートの場合は「ファイル → ダウンロード → Microsoft Excel (.xlsx)」で保存してください。
CSV の場合はファイル名がシート名として扱われます。

## シート名の規則と分類

| 分類 | category | シート名 | 例 |
|---|---|---|---|
| 大劇場公演 | `large` | `年_月日_大公演_公演名` | `2026_0121_大公演_渤海` |
| それ以外の公演 | `small` | `年_月日_小公演_公演名` | `2026_0415_小公演_春の夢` |
| お茶会 | `tea_party` | `公演名_お茶会` | `渤海_お茶会` → large「渤海」に紐づけ |
| 親睦会 | `social` | `公演名_親睦会` | `春の夢_親睦会` → small「春の夢」に紐づけ |
| グッズ | `goods` | `公演名_グッズ` | `渤海_グッズ` → 同名の公演に紐づけ |
| 年間企画 | `annual` | `年_月日_企画名` | `2026_1201_クリスマス会` |

- 種別の書き方は `大公演 / 大劇場 / large` と `小公演 / 小劇場 / 別箱 / small` を受け付けます。全角・半角は問いません。
- 規則に合わないシート（`Sheet1` など）は取り込まず、`review.csv` に記録します。
- お茶会・親睦会の名前が公演名と違う場合は、`config/event_links.example.csv` を
  `config/event_links.csv` にコピーして紐づけ先を指定してください。

## 列名

`name(漢字) / name katakana / Family name / First name / mail / phone-number / post-number / prefecture / address 1 / address 2`
＋ 金額列（公演: `Ticket` `Support`、お茶会: `Entry_fee`、親睦会・年間企画・グッズ: `total_cost`）。

よくある言い換えにも対応しています（例: 氏名・名前 / フリガナ / メールアドレス / 電話番号 / 郵便番号 / 住所 / チケット代 / 応援 / 参加費 / 合計金額 など）。
シートの上にタイトル行があっても、ヘッダ行を自動で探します。

## 自動で揃える内容

- 全角・半角、余分な空白
- フリガナ: ひらがな → カタカナ
- 電話番号: 数字のみ（Excel で消えた先頭の 0 を補完、+81 表記にも対応）
- 郵便番号: `123-4567` 形式（先頭 0 の欠けを補完）
- 都道府県: `東京` → `東京都`。空欄なら住所の先頭から取り出す
- 金額: `¥12,000円` → `12000`
- メール: 小文字に統一
- 「合計」行や空行は除外

## 名寄せ（同一人物の判定）

**名前（漢字またはカナ）＋ 連絡先（メール・電話・郵便番号のどれか）** が一致すれば同一人物とします。
家族で連絡先を共有していても別人として扱えるよう、連絡先だけでは結びつけません。
同姓同名で連絡先が一致しない人は、`review.csv` に「同一人物か確認してください」と出します。

## 出力（`output/`）

| ファイル | 内容 |
|---|---|
| `events.csv` | イベント一覧。分類、日付、紐づけ先 (`linked_event_id`)、large/small/annual ごとの日付順通し番号 (`seq`) |
| `persons.csv` | 人物一覧（各項目は最新イベントの値）と参加イベント数 |
| `spending.csv` | 1行 = 人 × イベント × 費目（ticket / support / entry_fee / total_cost）の金額 |
| `summary.csv` | 人ごとの分類別合計金額 |
| `review.csv` | 要確認事項（不正な値、紐づけ不可、同姓同名など）。シート名と行番号付き |
| `formatted.xlsx` | 上記をまとめた Excel |

## 配分算出用のイベント抽出

```python
from takarazuka_data.pipeline import select_events
# 直近2回の large、直近2回の small、直近1回の annual と、それらに紐づくお茶会・親睦会・グッズ
sel = select_events(result.events, n_large=2, n_small=2, n_annual=1)
```

## テスト

```bash
python3 -m unittest discover -s tests -t .
```
