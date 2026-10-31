"""列名のゆれを吸収し、値を正規化する。"""
from __future__ import annotations

import math
import re
import unicodedata

from datetime import date, datetime

from .classify import ANNUAL, APPLICATION, GOODS, LARGE, POST_SALE, REFUND, ROSTER, SMALL, SOCIAL, TEA_PARTY, normalize_text

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
    "line_id",
]
AMOUNT_FIELDS = ["ticket", "support", "entry_fee", "total_cost"]
# 公演・申請シートで任意に使える列
TICKET_FIELDS = ["seat_type", "quantity", "show_date", "show_time", "alt_dates"]
MULTI_FIELDS = {"alt_dates"}  # 複数列（振替1, 振替2 ...）をまとめて受け取る

# 席種: large は SS/S/A/B、small は S のみ。申請時は席種未確定のため SS（small は S）で受け付ける
SEAT_TYPES = {LARGE: ["SS", "S", "A", "B"], SMALL: ["S"]}
DEFAULT_SEAT = {LARGE: "SS", SMALL: "S"}

# 種別ごとに期待する金額列
EXPECTED_AMOUNTS = {
    LARGE: ["ticket", "support"],
    SMALL: ["ticket", "support"],
    TEA_PARTY: ["entry_fee"],
    SOCIAL: ["total_cost"],
    ANNUAL: ["total_cost"],
    GOODS: ["total_cost"],
    POST_SALE: ["total_cost"],
    REFUND: ["total_cost"],
    APPLICATION: ["support"],  # サポート代（見込額）
    ROSTER: [],  # 名簿は連絡先のみ
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
    "line_id": ["lineid", "lineuserid", "lineユーザーid", "userid", "ラインid", "lineアカウントid"],
    "ticket": ["ticket", "チケット", "チケット代", "チケット金額", "チケット代金"],
    "support": ["support", "応援", "応援金", "応援費", "サポート", "サポート代", "サポート代(見込額)", "サポート見込額",
                "見込額", "お花代", "花代", "支援", "支援金"],
    "seat_type": ["seattype", "seat", "席種", "座席", "席", "希望席種", "確定席種"],
    "quantity": ["quantity", "qty", "count", "tickets", "枚数", "申込枚数", "希望枚数", "申請枚数", "確定枚数"],
    "show_date": ["showdate", "date", "datetime", "公演日", "公演日時", "観劇日", "観劇日時", "希望日", "希望日時",
                  "日程", "日時", "第1希望"],
    "show_time": ["showtime", "time", "時間", "開演", "開演時間", "公演時間", "回"],
    "alt_dates": ["altdates", "alternative", "振替", "振替日程", "振替希望", "振替日", "振替1", "振替2", "振替3",
                  "第2希望", "第3希望", "第4希望", "第5希望"],
    "entry_fee": ["entryfee", "entry", "参加費", "会費", "参加料", "お茶会費"],
    "total_cost": ["totalcost", "total", "cost", "合計", "合計金額", "金額", "総額", "購入金額",
                   "ご協力金額", "協力金額", "ご協力金", "協力金", "ご入金額", "入金額", "返金額", "返金金額"],
}


def header_key(h) -> str:
    s = unicodedata.normalize("NFKC", str(h)).lower()
    return re.sub(r"[\s_\-・/]", "", s)


ALIAS_TO_FIELD = {header_key(a): f for f, aliases in _ALIASES.items() for a in aliases}


def map_header(h, contains: bool = True) -> str | None:
    if h is None or (isinstance(h, float) and math.isnan(h)):
        return None
    key = header_key(h)
    if key in ALIAS_TO_FIELD:
        return ALIAS_TO_FIELD[key]
    if not contains or _looks_like_data(str(h)):
        return None
    # LINE のフォーム等で「希望枚数を入力してください」のような長い列名にも対応（最長一致、3文字以上）
    hits = [a for a in _CONTAINS_ALIASES if a in key]
    return ALIAS_TO_FIELD[max(hits, key=len)] if hits else None


_CONTAINS_ALIASES = [a for a in ALIAS_TO_FIELD if len(a) >= 3]


def _looks_like_data(h: str) -> bool:
    """メールアドレス・数字の多い値・長い文章は列名とみなさない（データ行をヘッダと誤認しないため）。"""
    s = unicodedata.normalize("NFKC", h)
    return "@" in s or bool(re.search(r"\d{3,}", s)) or len(s) > 40


def add_aliases(mapping: dict) -> None:
    """独自の列名を追加する（config/column_aliases.csv から読み込む）。"""
    for header, field in mapping.items():
        ALIAS_TO_FIELD[header_key(header)] = field
        if len(header_key(header)) >= 3 and header_key(header) not in _CONTAINS_ALIASES:
            _CONTAINS_ALIASES.append(header_key(header))


def load_aliases(path) -> int:
    """config/column_aliases.csv : header,field  （field は name_kanji / phone / ticket など）"""
    import pandas as pd
    from pathlib import Path
    path = Path(path)
    if not path.exists():
        return 0
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    valid = set(PERSON_FIELDS) | set(AMOUNT_FIELDS) | set(TICKET_FIELDS)
    mapping = {h: f.strip() for h, f in zip(df["header"], df["field"]) if h and f.strip() in valid}
    add_aliases(mapping)
    return len(mapping)


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


def clean_seat(v, perf_category: str) -> tuple[str, str | None]:
    """席種を SS/S/A/B に揃える。空欄は申請時の既定 (large: SS, small: S)。"""
    default = DEFAULT_SEAT.get(perf_category, "SS")
    s = clean_text(v).upper().replace("席", "").replace(" ", "")
    if not s:
        return default, None
    allowed = SEAT_TYPES.get(perf_category, SEAT_TYPES[LARGE])
    if s in allowed:
        return s, None
    if perf_category == SMALL:
        return default, f"小公演の席種は S のみです（{s} → S）"
    return s, f"不明な席種です: {s}"


def clean_quantity(v) -> tuple[int, str | None]:
    if is_blank(v):
        return 1, "枚数が空欄のため 1 枚としました"
    n, err = clean_amount(re.sub(r"枚", "", clean_text(v)))
    if err or n <= 0:
        return 0, "枚数が不正です"
    return n, None


_DATE_RE = re.compile(r"(?:(\d{4})[/\-年.])?(\d{1,2})[/\-月.](\d{1,2})日?")
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2})|時(?:(\d{1,2})分?|(半))?)")


def clean_time(v) -> str:
    if is_blank(v):
        return ""
    if hasattr(v, "hour") and not isinstance(v, (date, datetime)):  # datetime.time
        return f"{v.hour:02d}:{v.minute:02d}"
    s = clean_text(v)
    m = _TIME_RE.search(s)
    if not m:
        return ""
    minute = m.group(2) or m.group(3) or ("30" if m.group(4) else "0")
    return f"{int(m.group(1)):02d}:{int(minute):02d}"


def parse_show(v, ref: date | None) -> tuple[date | None, str, str | None]:
    """公演日時を (日付, 'HH:MM', エラー) にする。年の省略時は ref（申請シートの日付）から補う。"""
    if is_blank(v):
        return None, "", None
    if isinstance(v, datetime):
        t = "" if (v.hour, v.minute) == (0, 0) else f"{v.hour:02d}:{v.minute:02d}"
        return v.date(), t, None
    if isinstance(v, date):
        return v, "", None
    s = clean_text(v)
    m = _DATE_RE.search(s)
    if not m:
        return None, "", f"公演日を読み取れません: {s}"
    month, day = int(m.group(2)), int(m.group(3))
    if m.group(1):
        year = int(m.group(1))
    elif ref:  # 申請シートの日付より前の月なら翌年とみなす
        year = ref.year + (1 if month < ref.month else 0)
    else:
        year = date.today().year
    try:
        d = date(year, month, day)
    except ValueError:
        return None, "", f"公演日が不正です: {s}"
    return d, clean_time(s[m.end():]), None


def split_alternatives(values) -> list:
    """振替日程（複数列・1セル内の複数指定）を1件ずつに分ける。"""
    out = []
    for v in values:
        if is_blank(v):
            continue
        if isinstance(v, (date, datetime)):
            out.append(v)
            continue
        out += [p for p in re.split(r"[,、\n;；]|\s{2,}", clean_text(v) if "\n" not in str(v) else str(v)) if p.strip()]
    return out
