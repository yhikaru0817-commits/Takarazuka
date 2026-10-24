"""相談・共有用に、個人情報を架空の値に置き換えたコピーを作る（ローカル専用）。

書式のくせ（全角/半角、空白、ハイフン、先頭 0 落ち、ひらがな/カタカナ等）は残したまま、
中身だけを置き換える。同じ人は同じ架空の値になるので、名寄せの確認にも使える。

置き換えには実行ごとにランダムな鍵を使い、鍵は保存しない。
そのため架空の値から元の値を逆算することはできない。

使い方: python -m takarazuka_data.mask [入力フォルダ] [-o 出力フォルダ]
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import numbers
import re
import secrets
import unicodedata
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

from .classify import name_key
from .columns import PREFECTURES, clean_prefecture, is_blank, map_header, to_katakana
from .pipeline import find_header, read_sheets

KANJI_POOL = "架空試験仮例山川田村林森野原沢谷花春夏秋冬月星雪風空海光音"
KANA_POOL = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワ"
ALPHA_POOL = "abcdefghijklmnopqrstuvwxyz"


class Masker:
    def __init__(self):
        self.key = secrets.token_bytes(32)  # 実行ごとに生成し、保存しない

    def _stream(self, kind: str, basis: str):
        """(種類, 元の値の正規化キー) から決まる疑似乱数列。"""
        counter = 0
        while True:
            digest = hmac.new(self.key, f"{kind}|{basis}|{counter}".encode(), hashlib.sha256).digest()
            yield from digest
            counter += 1

    # --- 種類別の置き換え ---

    def _letters(self, original: str, kind: str, basis: str, pool: str, keep) -> str:
        rnd = self._stream(kind, basis)
        return "".join(c if keep(c) else pool[next(rnd) % len(pool)] for c in original)

    def name(self, v: str) -> str:
        """漢字氏名: 空白の位置と文字数を保つ。"""
        return self._letters(v, "name", name_key(v), KANJI_POOL, keep=str.isspace)

    def kana(self, v: str) -> str:
        """フリガナ: ひらがな/カタカナの別と空白を保つ。"""
        fake = self._letters(v, "kana", name_key(to_katakana(v)), KANA_POOL, keep=str.isspace)
        return "".join(chr(ord(f) - 0x60) if "ぁ" <= o <= "ゖ" and "ァ" <= f <= "ヶ" else f
                       for o, f in zip(v, fake))

    def roman(self, v: str) -> str:
        """ローマ字: 大文字/小文字を保つ。ローマ字以外（漢字の姓など）は氏名扱い。"""
        if not re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ\s.'\-]+", v):
            return self.name(v)
        rnd = self._stream("roman", v.lower())
        out = []
        for c in v:
            if c.isalpha():
                f = ALPHA_POOL[next(rnd) % 26]
                out.append(f.upper() if c.isupper() else f)
            else:
                out.append(c)
        return "".join(out)

    def digits(self, v, kind: str):
        """電話・郵便番号: 桁数・区切り・全角を保ち、先頭 1 桁は残す（0 落ちの確認用）。"""
        if isinstance(v, numbers.Number) and not isinstance(v, bool):
            s = str(int(v)) if float(v).is_integer() else str(v)
            return int(self.digits(s, kind))
        s = str(v)
        plain = re.sub(r"\D", "", unicodedata.normalize("NFKC", s))
        rnd = self._stream(kind, plain)
        out, first = [], True
        for c in s:
            n = unicodedata.normalize("NFKC", c)
            if n.isdigit():
                d = n if first else str(next(rnd) % 10)
                first = False
                out.append(chr(ord("０") + int(d)) if c != n else d)
            else:
                out.append(c)
        return "".join(out)

    def email(self, v: str) -> str:
        s = str(v)
        local, at, _domain = s.partition("@")
        fake = self._letters(local, "mail", s.strip().lower(), ALPHA_POOL + "0123456789",
                             keep=lambda c: not c.isalnum())
        if any(c.isupper() for c in local):
            fake = fake[:1].upper() + fake[1:]
        return fake + (at + "example.com" if at else "")

    def line_id(self, v: str) -> str:
        return self._letters(v, "line", v.strip(), "0123456789abcdef", keep=lambda c: not c.isalnum() or c == "U")

    def address(self, v: str) -> str:
        """住所: 先頭の都道府県と区切り記号は残し、文字は〇、数字は架空の数字にする。"""
        s = str(v)
        pref = next((p for p in PREFECTURES if s.startswith(p)), "")
        rest = s[len(pref):]
        rnd = self._stream("addr", rest)
        out = []
        for c in rest:
            n = unicodedata.normalize("NFKC", c)
            if n.isdigit():
                out.append(str(next(rnd) % 10) if c == n else chr(ord("０") + next(rnd) % 10))
            elif c.isalpha():
                out.append("〇")
            else:
                out.append(c)
        return pref + "".join(out)

    def opaque(self, v):
        """内容が分からない列（備考・LINE表示名など）: 日付・数値以外は伏せ字にする。"""
        if isinstance(v, (date, datetime, time, pd.Timestamp)):
            return v
        if isinstance(v, numbers.Number):
            return safe_number(v, self)
        return "■" * min(len(str(v)), 8)


FIELD_MASK = {
    "name_kanji": Masker.name, "name_kana": Masker.kana,
    "family_name": Masker.roman, "first_name": Masker.roman,
    "email": Masker.email, "line_id": Masker.line_id, "address1": Masker.address, "address2": Masker.address,
}
AMOUNT_LIKE = {"ticket", "support", "entry_fee", "total_cost", "quantity"}
DATE_LIKE = {"show_date", "show_time", "alt_dates"}

# 「安全と確認できた値だけ残し、それ以外はすべて伏せる」方針。
# 列の途中で並びがずれていても、想定外の値は伏せ字になる。
_AMOUNT_RE = re.compile(r"^[\s¥￥\d,，.．円枚\-－+]*$")
_STRICT_DATE_RE = re.compile(
    r"^(?:\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?|\d{1,2}[/月]\d{1,2}日?)?"   # 2026-01-21 / 2026年1月21日 / 1/21
    r"\s*(?:[(（]?[月火水木金土日]曜?日?[)）]?)?"                              # (水)
    r"\s*(?:\d{1,2}(?::\d{2}(?::\d{2})?|時(?:\d{1,2}分)?|時半))?$")         # 15:00 / 11時00分
_PHONE_RE = re.compile(r"^[\d０-９\s\-－ー‐()（）+〒]*$")
_SEAT_RE = re.compile(r"^(SS|S|A|B)席?$")
# 列名として残してよい語（実在の氏名にまず含まれない語）
_LABEL_WORDS = ("金額", "代金", "日付", "日時", "備考", "人数", "枚数", "会費", "返金", "席", "番号", "参加", "名義",
                "合計", "時間", "公演", "メモ", "サポート", "協力", "グッズ", "チケット", "写真", "振込", "入金", "申込",
                "曜", "開演", "1枚あたり", "金", "数", "購入", "販売", "支払", "送付", "状況", "済", "希望", "振替",
                "区分", "種別", "No", "№")


def safe_number(v, m: Masker, limit: int = 100_000):
    """金額・人数・日付のシリアル値などの小さい数は残し、電話番号のような大きい数は架空の数字にする。"""
    if isinstance(v, bool) or abs(v) < limit:
        return v
    return m.digits(v, "num")


def safe_label(v, m: Masker):
    """列名の行: 既知の列名と、ラベルらしい語を含む短い文字列だけ残す。"""
    if not isinstance(v, str):
        return safe_number(v, m) if isinstance(v, numbers.Number) else v
    s = unicodedata.normalize("NFKC", v).strip()
    if "@" in s or re.search(r"\d{3,}", s) or len(s) > 30:
        return m.opaque(v)
    if map_header(s, contains=False) or any(w in s for w in _LABEL_WORDS):
        return v
    return m.opaque(v)


def safe_value(v, field, m: Masker):
    if isinstance(v, (date, datetime, time, pd.Timestamp)):
        return v
    if isinstance(v, numbers.Number):
        return safe_number(v, m, 1_000_000 if field in AMOUNT_LIKE else 100_000)
    s = str(v)
    n = unicodedata.normalize("NFKC", s).strip()
    if field in FIELD_MASK:
        return FIELD_MASK[field](m, s)
    if field in ("phone", "postal_code"):
        return m.digits(s, field) if _PHONE_RE.match(n) else m.opaque(v)
    if field in AMOUNT_LIKE and _AMOUNT_RE.match(n) and not re.search(r"\d{7,}", n.replace(",", "")):
        return v
    if field == "prefecture" and clean_prefecture(n) in PREFECTURES:
        return v
    if field == "seat_type" and _SEAT_RE.match(n.upper()):
        return v
    if _STRICT_DATE_RE.match(n) and re.search(r"\d", n):  # 日付・時刻だと形で確かめられるものだけ
        return v
    return m.opaque(v)


def mask_sheet(df: pd.DataFrame, m: Masker) -> pd.DataFrame:
    out = df.astype(object)
    header_row, mapping = find_header(df)
    start = 0 if header_row is None else header_row + 1
    for r in range(len(df)):
        for ci, col in enumerate(df.columns):
            v = df.iat[r, ci]
            if is_blank(v):
                continue
            if r == header_row:
                out.iat[r, ci] = safe_label(v, m)
                continue
            field = mapping.get(col) if r >= start else None
            out.iat[r, ci] = safe_value(v, field, m)
            # 最後の安全確認: 実在のメールアドレスらしき値は必ず伏せる
            o = out.iat[r, ci]
            if isinstance(o, str) and "@" in o and not o.strip().lower().endswith("@example.com"):
                out.iat[r, ci] = m.opaque(o)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="個人情報を架空の値に置き換えたコピーを作ります（ネット通信なし）")
    ap.add_argument("input", nargs="?", default="data/raw")
    ap.add_argument("-o", "--output", default="masked")
    args = ap.parse_args(argv)

    src, dst = Path(args.input), Path(args.output)
    paths = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv") and not p.name.startswith("~$"))
    dst.mkdir(parents=True, exist_ok=True)
    m = Masker()
    books: dict[str, dict] = {}
    for sheet_name, df, file_name in read_sheets(paths):
        books.setdefault(file_name, {})[sheet_name] = mask_sheet(df, m)
    for file_name, sheets in books.items():
        if file_name.lower().endswith(".csv"):
            df = next(iter(sheets.values()))
            df.to_csv(dst / file_name, header=False, index=False, encoding="utf-8-sig")
        else:
            with pd.ExcelWriter(dst / (Path(file_name).stem + ".xlsx")) as w:
                for sheet_name, df in sheets.items():
                    df.to_excel(w, sheet_name=sheet_name[:31], header=False, index=False)
    print(f"{len(books)} ファイルを {dst}/ に出力しました。")
    print("送る前に必ず中身を開いて、個人情報が残っていないか目で確認してください。")


if __name__ == "__main__":
    main()
