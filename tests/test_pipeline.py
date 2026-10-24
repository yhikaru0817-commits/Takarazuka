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


def person(kanji, kana, mail, phone, zip_, pref="大阪府"):
    return [kanji, kana, "", "", mail, phone, zip_, pref, "架空市1-2-3", ""]


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
        self.assertTrue(self.result.review["message"].str.contains("同姓同名").any())

    def test_amounts(self):
        s = self.result.summary.set_index("person_id")
        hanako_id = self.result.persons.query("name_kana == 'カクウ ハナコ'")["person_id"].iloc[0]
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
        hanako = req[req["person_id"] == p.at["カクウ ハナコ", "person_id"]].iloc[0]
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
