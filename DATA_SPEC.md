# 整形後のデータ仕様（顧客マスターを作る方向け）

このツールの役割は、**バラバラな形式のシートを、決まった形式の表に整えること**です。
顧客マスターの作成（同一人物の判定・顧客番号の付与）は、このツールの範囲外です。整形後のデータを入力にして作ってください。

## 渡すファイル（`data/` フォルダ）
| ファイル | 内容 |
|---|---|
| `standardized_all.csv` | **全シートの行を1つにした表。まずこれを使います。** どのシートの何行目かも分かります。 |
| `sheet_index.csv` | 整形後のシートの一覧（種別・日付・公演名・紐づく公演・行数・金額の合計・元のシート名） |
| `raw/*.csv` | 整形後のシートごとのCSV（上の表を、シートごとに分けたもの） |
| `sheet_map.csv` | 元のシートと、種別・日付・公演名の対応表（人が確認・修正した内容） |

すべて UTF-8（BOM付き）のCSVです。個人情報が入っているので、外部のサービスには送らないでください。

## standardized_all.csv の列
| 列 | 内容 |
|---|---|
| `sheet` | 整形後のシート名。`年_月日_タグ_名前`（公演・年間企画）または `タグ_名前`（`sheet_index.csv` の `sheet` と同じ） |
| `category` | イベントの種別（下の表） |
| `event_name` | 公演名・企画名（略称。お茶会・親睦会・グッズは、紐づく公演と同じ名前） |
| `event_date` | 日付 `YYYYMMDD`（公演・年間企画のみ。ほかは空） |
| `linked_sheet` | お茶会・親睦会・グッズが紐づく公演のシート名（紐づかないものは空） |
| `row_type` | 行の元の種別。**`refund`（返金）は、`goods` のシートに加えた行で、金額はマイナス** |
| `source_sheet`, `source_row` | 元のシート名と、元の行番号（見出しが1行目） |
| `name(漢字)` | 名前（1列。姓と名の間は空白1つ） |
| `name katakana` | フリガナ（カタカナにそろえてある） |
| `Family name`, `First name` | 姓・名（元のシートに別の列があった場合のみ） |
| `mail` | メール（小文字） |
| `phone-number` | 電話（数字だけ。先頭の0を補ってある） |
| `post-number` | 郵便番号（`123-4567`） |
| `prefecture` | 都道府県（`東京` → `東京都`） |
| `address 1` | 住所（市区町村・町名・番地。**複数の列に分かれていた場合は結合済み**） |
| `address 2` | 建物名など |
| `Ticket`, `Support`, `total_cost` | 金額（円・整数）。種別ごとに使う列が決まっています（下の表） |
| `枚数`, `席種`, `LINE ID` | 元のシートにあった場合のみ |

## 種別（category）と金額の列
| category | 意味 | 金額の列 | 紐づけ |
|---|---|---|---|
| `large` | 大劇場公演のチケット | `Ticket`（チケット代）、`Support`（サポート代＝お花代） | |
| `small` | それ以外の公演のチケット | `Ticket`、`Support` | |
| `tea` | お茶会 | `total_cost`（参加費） | 同じ公演名の公演 |
| `social` | 親睦会 | `total_cost` | 同じ公演名の公演（お茶会と同じ扱い） |
| `goods` | グッズ | `total_cost`（返金は `row_type` が `refund` の行で、マイナス） | 同じ公演名の `large` / `small` |
| `post_sale` | 事後販売 | `total_cost` | どの公演にも紐づけない |
| `annual` | 年間企画（誕生日企画・カレンダーなど） | `total_cost` | |
| `roster` | 名簿（連絡先だけ。金額は空・0） | なし | |

## 整形のルール（ツールが行ったこと）
- **1行 = 1人の1回の申込・支払い**です。同じ人が複数のシート・複数の行に出てきます。**同一人物の判定はしていません。**
- 金額は**その行の合計**です（1枚あたりではありません）。チケットの席種は、申請時は未確定のため SS（small は S）として受け付けています。
- 赤く塗られた行（キャンセル）は、除外してあります。
- 空行・合計の行・タイトルの行は除いてあります。氏名のない行も除いてあります。
- 複数のシートに分かれていた同じイベントは、1つのシートにまとめてあります。
- 休演の返金（ガイズ）: お茶会の参加費を `goods` として計上し、現金で返した額をマイナスで引いてあります。
- 公演名は略称です。同じ公演のお茶会・親睦会・グッズは、同じ略称で結びついています。

## 顧客マスターを作るときの参考
同一人物の判定は、このリポジトリの `takarazuka_data/identity.py` に参考実装があります（使わなくて構いません）。考え方は次のとおりです。
- **名前（漢字またはフリガナ）＋ 連絡先（メール・電話・住所のどれか）が一致**すれば、同一人物とみなす。連絡先だけでは結びつけない（家族で共有するため）。
- 連絡先のない行（名前だけ）は、同じ名前で連絡先のある人が**1人だけ**なら、その人に結びつける。
- 6人以上に共通する名前や連絡先（「なし」・代表のメールなど）は、本人を特定する値として使わない。
- 結婚・引っ越し・電話番号の変更で、名前や連絡先が変わっている人がいるので、**自動で結びつけずに、人が確認する組として出す**（同じメールで名前が違う、同じ名前で連絡先が全部違う、など）。
- 顧客番号は一度振ったら変えない。

---

# 付録: 参考実装の出力データ仕様（顧客マスター・配分システム向け。使うかどうかは任意）

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
| category | `large` / `small` / `tea`(お茶会) / `social`(親睦会) / `annual` / `goods` / `post_sale`(事後販売。公演に紐づけない) / `application`(今回の申請) |
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
`customer_id, large_ticket, large_support, small_ticket, small_support, tea, social, annual, goods, post_sale, support_total, total`
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
