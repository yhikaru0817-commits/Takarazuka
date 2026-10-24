"""テストはすべて架空のデータで行う（実データをリポジトリに置かないこと）。"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from takarazuka_data.classify import ANNUAL, GOODS, LARGE, SMALL, SOCIAL, TEA_PARTY, UNKNOWN, classify_sheet
from takarazuka_data.classify import APPLICATION
from takarazuka_data.columns import (
    clean_amount, clean_phone, clean_postal, clean_prefecture, clean_seat, map_header, parse_show)
from takarazuka_data.pipeline import run, select_events, write_outputs

STD = ["name(漢字)", "name katakana", "Family name", "First name", "mail", "phone-number",
       "post-number", "prefecture", "address 1", "address 2"]


class ClassifyTest(unittest.TestCase):
    def test_categories(self):
        cases = {
            "2026_0121_大公演_渤海": (LARGE, "渤海", date(2026, 1, 21)),
            "2026_0415_small_春の夢": (SMALL, "春の夢", date(2026, 4, 15)),
            "渤海_お茶会": (TEA_PARTY, "渤海", None),
            "春の夢_親睦会": (SOCIAL, "春の夢", None),
            "渤海_グッズ": (GOODS, "渤海", None),
            "2026_1201_クリスマス会": (ANNUAL, "クリスマス会", date(2026, 12, 1)),
            "２０２６＿０１２１＿大公演＿渤海": (LARGE, "渤海", date(2026, 1, 21)),  # 全角
        }
        for sheet, (cat, name, d) in cases.items():
            info = classify_sheet(sheet)
            self.assertEqual((info.category, info.name, info.event_date), (cat, name, d), sheet)

    def test_unknown_and_bad_date(self):
        self.assertEqual(classify_sheet("Sheet1").category, UNKNOWN)
        self.assertIsNotNone(classify_sheet("2026_1340_大公演_渤海").error)


class ColumnsTest(unittest.TestCase):
    def test_headers(self):
        self.assertEqual(map_header("name(漢字)"), "name_kanji")
        self.assertEqual(map_header("フリガナ"), "name_kana")
        self.assertEqual(map_header("phone-number"), "phone")
        self.assertEqual(map_header("Ｅｎｔｒｙ＿ｆｅｅ"), "entry_fee")
        self.assertEqual(map_header("住所①"), "address1")

    def test_values(self):
        self.assertEqual(clean_phone(9012345678)[0], "09012345678")
        self.assertEqual(clean_phone("０９０－１２３４－５６７８")[0], "09012345678")
        self.assertEqual(clean_postal(600000)[0], "060-0000")
        self.assertEqual(clean_postal("〒１２３ー４５６７")[0], "123-4567")
        self.assertEqual(clean_prefecture("東京"), "東京都")
        self.assertEqual(clean_amount("¥12,000円")[0], 12000)
        self.assertIsNotNone(clean_amount("abc")[1])

    def test_ticket_values(self):
        self.assertEqual(clean_seat("ｓｓ席", LARGE), ("SS", None))
        self.assertEqual(clean_seat("", LARGE)[0], "SS")  # 申請時は SS で受付
        self.assertEqual(clean_seat("", SMALL)[0], "S")  # small は S のみ
        self.assertIsNotNone(clean_seat("SS", SMALL)[1])
        self.assertEqual(parse_show("1/5(月) 13時半", date(2026, 11, 1))[:2], (date(2027, 1, 5), "13:30"))
        self.assertEqual(classify_sheet("2026_1105_大公演_星の詩_申請").category, APPLICATION)


def person(kanji, kana, mail, phone, zip_, pref="大阪府", addr=None):
    return [kanji, kana, "", "", mail, phone, zip_, pref, addr or f"架空市{phone}", ""]


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        a = person("架空 花子", "かくう はなこ", "Hanako@Example.com", 9000000001, "1000001")
        b = person("試験 太郎", "シケン タロウ", "taro@example.com", "080-0000-0002", "200-0002")
        a2 = person("架空　花子", "カクウ ハナコ", "", "090-0000-0001", "")  # 全角空白・メール無し
        c = person("試験 太郎", "シケン タロウ", "other@example.com", "070-0000-0003", "300-0003")  # 同姓同名別人

        with pd.ExcelWriter(d / "tickets.xlsx") as w:
            # タイトル行付き・列順バラバラのシート
            pd.DataFrame([["渤海 申込一覧", *[""] * 11], STD + ["Ticket", "Support"],
                          a + ["¥24,000", "5,000"], b + [12000, ""], ["合計", *[""] * 9, 36000, 5000]]
                         ).to_excel(w, sheet_name="2026_0121_大公演_渤海", header=False, index=False)
            pd.DataFrame([["名前", "フリガナ", "電話番号", "メール", "郵便番号", "チケット", "応援"],
                          [a2[0], a2[1], a2[5], "", "", 8000, 0]]
                         ).to_excel(w, sheet_name="2026_0415_小公演_春の夢", header=False, index=False)
            pd.DataFrame([STD + ["Ticket", "Support"], a + [30000, 10000], c + [6000, 0]]
                         ).to_excel(w, sheet_name="2026_0801_大公演_秋の詩", header=False, index=False)
        with pd.ExcelWriter(d / "events.xlsx") as w:
            pd.DataFrame([STD + ["Entry_fee"], a + [15000]]).to_excel(
                w, sheet_name="渤海_お茶会", header=False, index=False)
            pd.DataFrame([STD + ["total_cost"], b + [7000]]).to_excel(
                w, sheet_name="春の夢_親睦会", header=False, index=False)
            pd.DataFrame([STD + ["total_cost"], a + [3000]]).to_excel(
                w, sheet_name="2025_1220_クリスマス会", header=False, index=False)
            pd.DataFrame([STD + ["total_cost"], b + ["2,500"]]).to_excel(
                w, sheet_name="渤海_グッズ", header=False, index=False)
            pd.DataFrame([["メモ"]]).to_excel(w, sheet_name="Sheet1", header=False, index=False)
        cfg = d / "seat_prices.csv"
        cfg.write_text("category,seat_type,price,performance_sheet\nlarge,SS,12000,\nlarge,S,9000,\n",
                       encoding="utf-8")
        new = person("新規 由美", "シンキ ユミ", "yumi@example.com", "080-0000-0009", "400-0004")
        with pd.ExcelWriter(d / "apply.xlsx") as w:
            pd.DataFrame([STD + ["第1希望", "振替1", "振替2", "枚数", "席種", "サポート代（見込額）"],
                          a + ["11/12(木) 15:00", "11/13 11:00、11/14 15:00", "", 2, "", 20000],
                          new + ["11/15 13:00", "", "", "1枚", "S", ""]]
                         ).to_excel(w, sheet_name="2026_1105_大公演_星の詩_申請", header=False, index=False)
        self.prices = cfg
        self.result = run(sorted(d.glob("*.xlsx")), prices_path=d / "seat_prices.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_events_and_links(self):
        ev = self.result.events.set_index("sheet_name")
        self.assertEqual(len(ev), 8)
        self.assertEqual(ev.at["渤海_お茶会", "linked_event_id"], ev.at["2026_0121_大公演_渤海", "event_id"])
        self.assertEqual(ev.at["春の夢_親睦会", "linked_event_id"], ev.at["2026_0415_小公演_春の夢", "event_id"])
        self.assertEqual(ev.at["渤海_グッズ", "linked_event_id"], ev.at["2026_0121_大公演_渤海", "event_id"])
        self.assertEqual(ev.at["2026_0801_大公演_秋の詩", "seq"], 2)
        self.assertTrue((self.result.review["sheet"] == "Sheet1").any())

    def test_identity(self):
        p = self.result.persons
        hanako = p[p["name_kana"] == "カクウ ハナコ"]
        self.assertEqual(len(hanako), 1, "表記ゆれ・連絡先の欠けがあっても同一人物にまとめる")
        self.assertEqual(hanako.iloc[0]["event_count"], 5, "申請は実績に数えない")
        self.assertEqual(hanako.iloc[0]["email"], "hanako@example.com")
        self.assertEqual(len(p[p["name_kanji"] == "試験 太郎"]), 2, "同姓同名でも連絡先が違えば別人")
        mr = self.result.match_review
        self.assertEqual(len(mr), 1)
        self.assertEqual(mr.iloc[0]["reason"], "名前が同じで連絡先が違う")

    def test_amounts(self):
        s = self.result.summary.set_index("customer_id")
        hanako_id = self.result.persons.query("name_kana == 'カクウ ハナコ'")["customer_id"].iloc[0]
        self.assertEqual(s.at[hanako_id, "large_ticket"], 24000 + 30000)
        self.assertEqual(s.at[hanako_id, "large_support"], 5000 + 10000)
        self.assertEqual(s.at[hanako_id, "small_ticket"], 8000)
        self.assertEqual(s.at[hanako_id, "support_total"], 15000)
        self.assertEqual(s.at[hanako_id, TEA_PARTY], 15000)
        self.assertEqual(s.at[hanako_id, ANNUAL], 3000)
        self.assertEqual(int(self.result.spending["amount"].sum()), 24000 + 5000 + 12000 + 8000 + 30000
                         + 10000 + 6000 + 15000 + 7000 + 3000 + 2500)

    def test_applications(self):
        req = self.result.application_requests
        pref = self.result.application_preferences
        p = self.result.persons.set_index("name_kana")
        hanako = req[req["customer_id"] == p.at["カクウ ハナコ", "customer_id"]].iloc[0]
        self.assertEqual((hanako["quantity"], hanako["seat_type_requested"], hanako["support_expected"]), (2, "SS", 20000))
        self.assertEqual((hanako["ticket_price"], hanako["ticket_amount"]), (12000, 24000))
        choices = pref[pref["request_id"] == hanako["request_id"]]
        self.assertEqual(list(zip(choices["show_date"], choices["show_time"])), [
            (date(2026, 11, 12), "15:00"), (date(2026, 11, 13), "11:00"), (date(2026, 11, 14), "15:00")])
        self.assertTrue(bool(p.at["シンキ ユミ", "is_new"]))
        # 見込額は実績の spending に入れない
        self.assertFalse((self.result.spending["category"] == APPLICATION).any())

    def test_select_events(self):
        sel = select_events(self.result.events, n_large=1, n_small=1, n_annual=1)
        self.assertEqual(set(sel["sheet_name"]), {
            "2026_0801_大公演_秋の詩", "2026_0415_小公演_春の夢", "春の夢_親睦会", "2025_1220_クリスマス会"})

    def test_write(self):
        with tempfile.TemporaryDirectory() as out:
            files = write_outputs(self.result, Path(out))
            self.assertTrue(all(f.exists() for f in files))


if __name__ == "__main__":
    unittest.main()


class SeatPriceEstimateTest(unittest.TestCase):
    def test_estimate_from_history_and_csv_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            a = person("架空 花子", "カクウ ハナコ", "hanako@example.com", "090-0000-0001", "100-0001")
            b = person("試験 太郎", "シケン タロウ", "taro@example.com", "080-0000-0002", "200-0002")
            cols = STD + ["席種", "枚数", "Ticket", "Support"]
            pd.DataFrame([a + ["SS", 2, 20000, 0], b + ["S", 1, 8000, 0]], columns=cols).to_csv(
                d / "2025_0601_大公演_旧作.csv", index=False)
            # 価格改定後: 新しい公演の単価を採用する
            pd.DataFrame([a + ["SS", 1, 12500, 3000], b + ["SS", 3, 37500, 0]], columns=cols).to_csv(
                d / "2026_0121_大公演_渤海.csv", index=False)
            # LINE からの申請 CSV（長い列名・cp932）
            pd.DataFrame([a + ["11/12 15:00", "2", "", "10000"]],
                         columns=STD + ["第1希望の公演日時", "希望枚数を入力してください", "席種", "サポート代（見込額）"]
                         ).to_csv(d / "2026_1105_大公演_星の詩_申請.csv", index=False, encoding="cp932")
            r = run(sorted(d.glob("*.csv")))
        est = r.seat_price_estimates.set_index("seat_type")
        self.assertEqual(est.at["SS", "price"], 12500)
        self.assertEqual(est.at["SS", "price_variants"], "10000 / 12500")
        self.assertEqual(est.at["S", "price"], 8000)
        req = r.application_requests.iloc[0]
        self.assertEqual((req["quantity"], req["seat_type_requested"], req["ticket_amount"], req["support_expected"]),
                         (2, "SS", 25000, 10000))
        self.assertTrue(r.review["message"].str.contains("推定値").any())


class MaskTest(unittest.TestCase):
    def test_mask_keeps_format_but_not_values(self):
        from takarazuka_data.mask import Masker, mask_sheet
        m = Masker()
        raw = pd.DataFrame([
            ["渤海 申込一覧", "", "", "", "", "", "", ""],
            ["name(漢字)", "name katakana", "mail", "phone-number", "post-number", "address 1", "Ticket", "備考"],
            ["架空　花子", "かくう はなこ", "Hanako@Example.com", 9000000001, "〒100-0001", "大阪府架空市1-2-3", 12000, "友人と"],
            ["架空花子", "カクウハナコ", "hanako@example.com", "０９０－００００－０００１", "", "", 8000, ""],
        ])
        out = mask_sheet(raw, m)
        flat = " ".join(map(str, out.values.ravel()))
        for secret in ("花子", "ハナコ", "はなこ", "Hanako", "0001", "架空市", "友人", "渤海"):
            self.assertNotIn(secret, flat)
        self.assertEqual(list(out.iloc[1]), list(raw.iloc[1]), "列名は残す")
        self.assertEqual(out.iat[2, 0][2], "　", "全角空白の位置を保つ")
        self.assertEqual(out.iat[2, 0].replace("　", ""), out.iat[3, 0], "同じ人は同じ架空名")
        self.assertTrue(all("ぁ" <= c <= "ゖ" or c == " " for c in out.iat[2, 1]), "ひらがなはひらがなのまま")
        self.assertIsInstance(out.iat[2, 3], int)  # 先頭 0 落ちの数値のまま
        self.assertEqual(len(str(out.iat[2, 3])), 10)
        self.assertRegex(out.iat[3, 3], r"^０[０-９]{2}－[０-９]{4}－[０-９]{4}$")
        self.assertRegex(out.iat[2, 4], r"^〒1\d{2}-\d{4}$")
        self.assertTrue(out.iat[2, 5].startswith("大阪府"))
        self.assertTrue(out.iat[2, 2].endswith("@example.com"))
        self.assertEqual(out.iat[2, 6], 12000, "金額は残す")
        self.assertNotEqual(Masker().name("架空 花子"), m.name("架空 花子"), "実行ごとに鍵が変わる")


class MasterTest(unittest.TestCase):
    """顧客マスター: 番号の維持、人の判定（同一/別人）の反映。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.raw, self.master, self.out = self.d / "raw", self.d / "master", self.d / "out"
        self.raw.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, sheet, rows, extra=("Ticket", "Support")):
        pd.DataFrame(rows, columns=STD + list(extra)).to_csv(self.raw / f"{sheet}.csv", index=False)

    def run_cli(self):
        from takarazuka_data.__main__ import main
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            main([str(self.raw), "-o", str(self.out), "--master", str(self.master),
                  "--links", str(self.d / "none.csv"), "--prices", str(self.d / "none.csv")])
        return (pd.read_csv(self.out / "persons.csv", dtype=str).fillna(""),
                pd.read_csv(self.out / "match_review.csv", dtype=str).fillna(""))

    def test_ids_are_stable_and_matching_uses_address_variants(self):
        a = person("髙橋 花子", "タカハシ ハナコ", "", "", "", addr="架空市中央1丁目2番3号")
        b = person("試験 太郎", "シケン タロウ", "taro@example.com", "", "")
        self.write("2026_0121_大公演_渤海", [b + [10000, 0], a + [12000, 1000]])
        persons, _ = self.run_cli()
        ids = dict(zip(persons["name_kana"], persons["customer_id"]))
        self.assertEqual(ids, {"シケン タロウ": "C00001", "タカハシ ハナコ": "C00002"})

        # 次回: 新しい人が先頭の行に来ても、既存の番号は変わらない。住所の表記ゆれ・異体字も同一人物
        new = person("新規 由美", "シンキ ユミ", "yumi@example.com", "", "")
        a2 = person("高橋 花子", "タカハシ ハナコ", "", "", "", addr="架空市中央1-2-3")
        self.write("2026_0415_小公演_春の夢", [new + [8000, 0], a2 + [8000, 500]])
        persons, _ = self.run_cli()
        ids = dict(zip(persons["name_kana"], persons["customer_id"]))
        self.assertEqual(ids, {"シケン タロウ": "C00001", "タカハシ ハナコ": "C00002", "シンキ ユミ": "C00003"})
        self.assertTrue(any((self.master / "backup").iterdir()), "上書き前にバックアップを取る")

    def test_review_decisions_are_applied_on_next_run(self):
        # 同じ電話で名前が違う（改姓など）→ 自動では結びつけず確認に回す
        a = person("架空 花子", "カクウ ハナコ", "", "090-0000-0001", "")
        a_new = person("試験 花子", "シケン ハナコ", "", "090-0000-0001", "")
        self.write("2026_0121_大公演_渤海", [a + [10000, 0]])
        self.write("2026_0415_小公演_春の夢", [a_new + [8000, 0]])
        persons, review = self.run_cli()
        self.assertEqual(len(persons), 2)
        self.assertIn("電話が同じで名前が違う", review.iloc[0]["reason"])

        review.loc[0, "decision"] = "同一"
        review.to_csv(self.out / "match_review.csv", index=False, encoding="cp932")  # Excel で保存した想定
        persons, review = self.run_cli()
        self.assertEqual(len(persons), 1, "「同一」と書いた組は統合される")
        self.assertEqual(persons.iloc[0]["customer_id"], "C00001")
        self.assertEqual(len(review), 0, "判定済みの組は再び聞かない")
        summary = pd.read_csv(self.out / "summary.csv")
        self.assertEqual(int(summary["total"].sum()), 18000)

    def test_line_id_links_people(self):
        a = person("架空 花子", "カクウ ハナコ", "", "", "")
        self.write("2026_0121_大公演_渤海", [a + ["U0123abcd", 10000, 0]], extra=("LINE ID", "Ticket", "Support"))
        a2 = person("架空花子", "", "", "", "")
        self.write("2026_0415_小公演_春の夢", [a2 + ["U0123abcd", 8000, 0]], extra=("LINE ID", "Ticket", "Support"))
        persons, _ = self.run_cli()
        self.assertEqual(len(persons), 1)
        self.assertEqual(persons.iloc[0]["line_id"], "U0123abcd")
