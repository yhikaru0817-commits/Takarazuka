"""列名のゆれを吸収し、値を正規化する。"""
from __future__ import annotations

import math
import re
import unicodedata

from .classify import ANNUAL, GOODS, LARGE, SMALL, SOCIAL, TEA_PARTY, normalize_text

PERSON_FIELDS = [
    "name_kanji",
    "name_kana",
    "family_name",
    "first_name",
    "email",
    "phone",
    "postal_code",
    "prefecture",
    "address1",
    "address2",
]
AMOUNT_FIELDS = ["ticket", "support", "entry_fee", "total_cost"]

# 種別ごとに期待する金額列
EXPECTED_AMOUNTS = {
    LARGE: ["ticket", "support"],
    SMALL: ["ticket", "support"],
    TEA_PARTY: ["entry_fee"],
    SOCIAL: ["total_cost"],
    ANNUAL: ["total_cost"],
    GOODS: ["total_cost"],
}

_ALIASES = {
    "name_kanji": ["name(漢字)", "name漢字", "name", "名前", "氏名", "お名前", "名前(漢字)", "氏名(漢字)", "漢字"],
    "name_kana": ["namekatakana", "namekana", "katakana", "kana", "カナ", "フリガナ", "ふりがな",
                  "カタカナ", "よみがな", "氏名カナ", "名前カナ", "名前(カナ)", "氏名(カナ)", "name(カナ)"],
    "family_name": ["familyname", "lastname", "surname", "姓", "苗字", "名字"],
    "first_name": ["firstname", "givenname", "名"],
    "email": ["mail", "email", "e-mail", "mailaddress", "emailaddress", "メール", "メールアドレス", "アドレス"],
    "phone": ["phonenumber", "phone", "tel", "telephone", "電話", "電話番号", "携帯", "携帯番号", "連絡先"],
    "postal_code": ["postnumber", "postcode", "postalcode", "zip", "zipcode", "郵便番号", "〒"],
    "prefecture": ["prefecture", "pref", "都道府県", "県"],
    "address1": ["address1", "address", "住所1", "住所", "市区町村", "住所(市区町村)"],
    "address2": ["address2", "住所2", "建物名", "番地以降", "住所(建物名)"],
    "ticket": ["ticket", "チケット", "チケット代", "チケット金額", "チケット代金"],
    "support": ["support", "応援", "応援金", "サポート", "支援", "支援金"],
    "entry_fee": ["entryfee", "entry", "参加費", "会費", "参加料", "お茶会費"],
    "total_cost": ["totalcost", "total", "cost", "合計", "合計金額", "金額", "総額", "購入金額"],
}


def header_key(h) -> str:
    s = unicodedata.normalize("NFKC", str(h)).lower()
    return re.sub(r"[\s_\-・/]", "", s)


ALIAS_TO_FIELD = {header_key(a): f for f, aliases in _ALIASES.items() for a in aliases}


def map_header(h) -> str | None:
    if h is None or (isinstance(h, float) and math.isnan(h)):
        return None
    return ALIAS_TO_FIELD.get(header_key(h))


# ---------- 値の正規化 ----------

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
    "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
_PREF_SHORT = {re.sub(r"[都府県]$", "", p): p for p in PREFECTURES if p != "北海道"}
_PREF_SHORT["北海道"] = "北海道"


def is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() == ""


def clean_text(v) -> str:
    if is_blank(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return normalize_text(v)


def to_katakana(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def clean_kana(v) -> str:
    return to_katakana(clean_text(v))


def clean_email(v) -> str:
    return clean_text(v).replace(" ", "").lower()


def _digits(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\D", "", unicodedata.normalize("NFKC", str(v)))


def clean_phone(v) -> tuple[str, str | None]:
    """数字のみの文字列にする。Excel で先頭 0 が落ちたものは補完する。"""
    if is_blank(v):
        return "", None
    d = _digits(v)
    if d.startswith("81") and len(d) in (11, 12):  # +81 表記
        d = "0" + d[2:]
    if len(d) in (9, 10) and not d.startswith("0"):
        d = "0" + d
    if len(d) not in (10, 11):
        return d, "電話番号の桁数が不正です"
    return d, None


def clean_postal(v) -> tuple[str, str | None]:
    if is_blank(v):
        return "", None
    d = _digits(v)
    if len(d) == 6:  # 先頭 0 落ち (例: 北海道 0xx-xxxx)
        d = "0" + d
    if len(d) != 7:
        return d, "郵便番号の桁数が不正です"
    return f"{d[:3]}-{d[3:]}", None


def clean_prefecture(v) -> str:
    s = clean_text(v).replace(" ", "")
    if not s:
        return ""
    if s in PREFECTURES:
        return s
    return _PREF_SHORT.get(s, s)


def split_prefecture(address: str) -> tuple[str, str]:
    """住所の先頭に都道府県があれば切り出す。"""
    for p in PREFECTURES:
        if address.startswith(p):
            return p, address[len(p):].strip()
    return "", address


def clean_amount(v) -> tuple[int, str | None]:
    if is_blank(v):
        return 0, None
    if isinstance(v, (int, float)):
        return int(round(v)), None
    s = unicodedata.normalize("NFKC", str(v))
    s = re.sub(r"[¥￥円,\s]", "", s)
    if s in ("", "-", "なし", "無"):
        return 0, None
    try:
        return int(round(float(s))), None
    except ValueError:
        return 0, "金額が数値ではありません"
