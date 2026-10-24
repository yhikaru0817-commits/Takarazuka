# 出力データ仕様（配分システム向け）

`python -m takarazuka_data` が `output/` に出力する表の仕様です。配分システムはこの表を入力にしてください。
すべて UTF-8 (BOM 付き) の CSV で、同じ内容が `formatted.xlsx` にもシートとして入ります。
主キー・外部キーは `customer_id` / `event_id` / `request_id` です。
`customer_id`（`C00001` 形式）は顧客マスター `data/master/customers.csv` で管理され、**一度振られたら変わりません**。
統合された番号は `merged_into` に統合先が入り、出力には統合先の番号だけが出ます。

> 個人情報を含むのは `persons` のみです。配分計算は `customer_id` だけで完結させ、
> 氏名・連絡先は連絡時にだけ `persons` から引いてください。

## 実績（過去データ）

### events — イベント一覧
| 列 | 内容 |
|---|---|
| event_id | イベントID（例 `L_20260121大公演渤海`） |
| category | `large` / `small` / `tea_party`(お茶会) / `social`(親睦会) / `annual` / `goods` / `application`(今回の申請) |
| name | 公演名・イベント名 |
| event_date | シート名の日付（お茶会・親睦会・グッズは空） |
| link_category | お茶会→`large`、親睦会→`small`。application ではその公演の種別 (`large`/`small`) |
| linked_event_id | お茶会・親睦会・グッズが紐づく公演の event_id |
| seq | large / small / annual それぞれの日付順通し番号（1 = 最も古い） |
| effective_date | 実質の日付（紐づけ先の公演日付を引き継ぐ） |
| sheet_name, source_file | 元シート |

直近 n 回の抽出は `select_events(events, n_large, n_small, n_annual)` を使えます（紐づくお茶会・親睦会・グッズも含みます）。

### spending — 支払い実績（縦持ち）
1行 = 人 × イベント × 費目。`application`（見込額）は**含みません**。

| 列 | 内容 |
|---|---|
| customer_id, event_id, category | |
| item | `ticket`(チケット代) / `support`(サポート代＝お花代) / `entry_fee`(お茶会参加費) / `total_cost`(親睦会・年間企画・グッズ) |
| amount | 円（整数） |

### summary — 人ごとの合計（実績）
`customer_id, large_ticket, large_support, small_ticket, small_support, tea_party, social, annual, goods, support_total, total`
（全期間の合計。期間を絞る場合は `spending` を `select_events` の結果で絞って集計してください）

### ticket_history — 過去公演の申込実績
`customer_id, event_id, category, seat_type, quantity, ticket, support`
（`seat_type` / `quantity` は元シートに列がある場合のみ値が入ります）

## 今回のチケット申請

### application_requests — 1行 = 1申請
| 列 | 内容 |
|---|---|
| request_id | 申請ID（`event_id#元シートの行番号`） |
| event_id | 申請シートの event_id |
| performance_category | `large` / `small` |
| customer_id | |
| quantity | 申請枚数 |
| seat_type_requested | 申請時の席種。未確定のため large は `SS`、small は `S` が既定 |
| support_expected | サポート代（見込額）。**申請1件あたりの金額**（1枚あたりではない） |
| ticket_price | 申請席種の1枚あたり価格（`config/seat_prices.csv` から） |
| ticket_amount | quantity × ticket_price |
| preference_count | 第1希望＋振替の候補数 |

### application_preferences — 1行 = 希望日時の候補
| 列 | 内容 |
|---|---|
| request_id | |
| rank | 1 = 第1希望、2 以降 = 振替 |
| is_alternative | 振替なら true |
| show_date, show_time | 公演日 / 開演時刻 (`HH:MM`) |

## 席種と価格
- large: `SS / S / A / B`、small: `S` のみ。
- 価格の優先順: `config/seat_prices.csv` の公演指定行 → 同ファイルの共通行 → 過去データからの推定値。
- `seat_price_estimates` — 過去公演の チケット代 ÷ 枚数 から推定した1枚価格:
  `category, seat_type, price（最新公演で最多の単価）, sample_count, price_variants（過去に出た単価の一覧）, latest_event_id`
- 席種確定後の実際の金額は、確定席種 × 価格で配分システム側で再計算してください。

## persons — 人物（個人情報）
`customer_id, name_kanji, name_kana, family_name, first_name, email, phone, postal_code, prefecture, address1, address2, line_id, event_count, is_new`

## match_review — 同一人物か要確認の組
`customer_id_a, name_a, kana_a, customer_id_b, name_b, kana_b, reason, decision`（decision は人が「同一」「別人」を記入）
（`event_count` = 実績のあるイベント数、`is_new` = 実績なし）

## review — 要確認事項
`level (error / warning / info / review), sheet, row, message`。配分前に error と review を解消してください。
