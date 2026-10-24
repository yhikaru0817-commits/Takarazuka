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
import re
import secrets
import unicodedata
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd

from .classify import name_key
from .columns import PREFECTURES, is_blank, map_header, to_katakana
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
        if isinstance(v, (int, float)) and not isinstance(v, bool):
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
        if isinstance(v, (int, float, date, datetime, time, pd.Timestamp)) and not isinstance(v, bool):
            return v
        return "■" * min(len(str(v)), 8)


FIELD_MASK = {
    "name_kanji": Masker.name, "name_kana": Masker.kana,
    "family_name": Masker.roman, "first_name": Masker.roman,
    "email": Masker.email, "address1": Masker.address, "address2": Masker.address,
}
KEEP_FIELDS = {"prefecture", "ticket", "support", "entry_fee", "total_cost",
               "seat_type", "quantity", "show_date", "show_time", "alt_dates"}


def mask_sheet(df: pd.DataFrame, m: Masker) -> pd.DataFrame:
    out = df.copy()
    header_row, mapping = find_header(df)
    start = 0 if header_row is None else header_row + 1
    for r in range(len(df)):
        if r == header_row:
            continue  # 列名は残す
        for ci, col in enumerate(df.columns):
            v = df.iat[r, ci]
            if is_blank(v):
                continue
            field = mapping.get(col) if r >= start else None
            if field in KEEP_FIELDS:
                continue
            if field in ("phone", "postal_code"):
                out.iat[r, ci] = m.digits(v, field)
            elif field in FIELD_MASK:
                out.iat[r, ci] = FIELD_MASK[field](m, str(v))
            else:
                out.iat[r, ci] = m.opaque(v)  # タイトル行・未対応列・ヘッダ不明シート
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
