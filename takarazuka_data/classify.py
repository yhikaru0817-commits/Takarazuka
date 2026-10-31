"""シート名からイベント種別を判定する。

命名規則（標準）: 年_月日_タグ_名前    ※ 公演と年間企画は日付が必要。ほかは日付を省略できる（タグ_名前）
    large   大劇場公演           2026_0404_large_呂布宝塚
    small   それ以外の公演       2026_0121_small_雨にじむ渤海
    tea     お茶会               tea_呂布宝塚          （同じ名前の公演に紐づく）
    social  親睦会               2026_0125_social_雨にじむ渤海
    goods   グッズ               goods_呂布東京
    post_goods 事後販売          post_goods_呂布       （どの公演にも紐づけない。post_呂布 も可）
    refund  返金                 refund_ガイズ宝塚      （マイナスの金額として同じ名前のグッズに加える）
    roster  名簿（連絡先のみ）   roster_お礼状
    annual  年間企画             2026_0331_annual_誕生日企画   （タグなしの 2026_0331_誕生日企画 も可）
    今回のチケット申請 : year_date_種別_公演名_申請   例) 2026_1105_large_星の詩_申請
従来の形（公演名_親睦会 や 2026_0121_大公演_渤海）も読める。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

LARGE = "large"
SMALL = "small"
TEA_PARTY = "tea"  # お茶会（同じ名前の公演に紐づく）
SOCIAL = "social"  # 親睦会（同じ名前の公演に紐づく。お茶会と同じ扱い）
ANNUAL = "annual"
GOODS = "goods"
APPLICATION = "application"  # 今回のチケット申請（実績ではなく見込み）
ROSTER = "roster"  # 名簿（連絡先だけ。金額なし）
POST_SALE = "post_goods"  # 事後販売（公演のあとのグッズ販売など。どの公演にも紐づけない）
REFUND = "refund"  # 返金（取り込み時にマイナスの金額として、同じ公演名のグッズに加える）
UNKNOWN = "unknown"

# 公演種別キーワード（比較は NFKC + 小文字化後）
LARGE_KEYWORDS = {"large", "大公演", "大劇場", "大劇場公演"}
SMALL_KEYWORDS = {"small", "小公演", "小劇場", "別箱", "別箱公演"}

APPLICATION_SUFFIXES = ("申請", "申込", "チケット申請")

# サフィックス → (種別, 紐づけ先の公演種別)
SUFFIXES = {
    "お茶会": (TEA_PARTY, None),
    "親睦会": (SOCIAL, None),
    "グッズ": (GOODS, None),  # large/small どちらでも可
    "名簿": (ROSTER, None),  # 例) 会員_名簿
    "事後販売": (POST_SALE, None),  # 例) 呂布_事後販売
}

_DATED = re.compile(r"^(\d{4})_(\d{4})_(.+)$")

# 標準のタグ（小文字。日本語も可）
TAGS = {
    "large": LARGE, "大公演": LARGE, "大劇場": LARGE, "大劇場公演": LARGE,
    "small": SMALL, "小公演": SMALL, "小劇場": SMALL, "別箱": SMALL, "別箱公演": SMALL,
    "tea": TEA_PARTY, "お茶会": TEA_PARTY,
    "social": SOCIAL, "親睦会": SOCIAL,
    "goods": GOODS, "グッズ": GOODS,
    "post_goods": POST_SALE, "post": POST_SALE, "post_sale": POST_SALE, "事後販売": POST_SALE,
    "refund": REFUND, "返金": REFUND,
    "roster": ROSTER, "名簿": ROSTER,
    "annual": ANNUAL, "年間企画": ANNUAL,
}
# タグの中に _ があっても（post_goods）、1つのタグとして読む（長いタグから順に照合）
_TAG_ALT = "|".join(re.escape(t) for t in sorted(TAGS, key=len, reverse=True))
_TAGGED = re.compile(rf"^(?:(\d{{4}})_(\d{{4}})_)?({_TAG_ALT})_(.+)$", re.IGNORECASE)
_NEEDS_DATE = (LARGE, SMALL, ANNUAL)


def normalize_text(s: str) -> str:
    """全角/半角ゆれと前後空白を除去する。"""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", " ", s).strip()


def name_key(s: str) -> str:
    """名前同士の比較用キー（空白・記号を除去）。"""
    return re.sub(r"[\s_・\-]", "", normalize_text(s)).lower()


@dataclass
class SheetInfo:
    sheet_name: str
    category: str
    name: str  # 公演名 / イベント名 / 企画名
    event_date: date | None = None
    link_category: str | None = None  # 紐づけ先の公演種別
    error: str | None = None


def _parse_date(year: str, mmdd: str) -> date | None:
    try:
        return date(int(year), int(mmdd[:2]), int(mmdd[2:]))
    except ValueError:
        return None


def _parse_dated(text: str):
    """'2026_0121_xxx' → (date, 'xxx', error)。マッチしなければ None。"""
    m = _DATED.match(text)
    if not m:
        return None
    d = _parse_date(m.group(1), m.group(2))
    err = None if d else f"日付が不正です: {m.group(1)}_{m.group(2)}"
    return d, m.group(3), err


def _split_performance(rest: str):
    """'大公演_渤海' → (LARGE, '渤海')。種別キーワードでなければ None。"""
    if "_" not in rest:
        return None
    kind, name = rest.split("_", 1)
    kind = kind.lower()
    if kind in LARGE_KEYWORDS:
        return LARGE, name
    if kind in SMALL_KEYWORDS:
        return SMALL, name
    return None


def _parse_tagged(sheet_name: str, text: str):
    """'2026_0121_small_雨にじむ渤海' / 'tea_呂布宝塚' のように、タグが名前の前にある標準の形。"""
    m = _TAGGED.match(text)
    cat = TAGS.get(m.group(3).lower()) if m else None
    if not cat:
        return None
    name = re.sub(r"(?:[\s_]*\(\d{1,2}\)|_\d{1,2})$", "", m.group(4)).strip()  # 連番（(2) や _2）は同じイベント
    if not name:
        return SheetInfo(sheet_name, UNKNOWN, "", error="イベント名が空です")
    event_date, err = None, None
    if m.group(1):
        event_date = _parse_date(m.group(1), m.group(2))
        if event_date is None:
            err = f"日付が不正です: {m.group(1)}_{m.group(2)}"
    elif cat in _NEEDS_DATE:
        err = "公演・年間企画のシート名には日付（年_月日）が必要です"
    return SheetInfo(sheet_name, cat, name, event_date, None, error=err)


def classify_sheet(sheet_name: str) -> SheetInfo:
    text = normalize_text(sheet_name)
    text = re.sub(r"\s*_\s*", "_", text)
    m = re.match(r"^(.+_(?:お茶会|親睦会|グッズ|事後販売|名簿))[\s_]*\(?\d{1,2}\)?$", text)
    if m:  # '雨にじむ渤海_親睦会2' や '…_親睦会 (2)' のように連番が付いていても、同じ種別・同じイベントとして扱う
        text = m.group(1)

    for suffix in APPLICATION_SUFFIXES:
        if text.endswith("_" + suffix):
            dated = _parse_dated(text[: -(len(suffix) + 1)])
            perf = _split_performance(dated[1]) if dated else None
            if not perf:
                return SheetInfo(sheet_name, UNKNOWN, text,
                                 error="申請シートは 年_月日_大公演/小公演_公演名_申請 の形式にしてください")
            # link_category に公演種別 (large/small) を持たせる
            return SheetInfo(sheet_name, APPLICATION, perf[1], dated[0], perf[0], error=dated[2])

    tagged = _parse_tagged(sheet_name, text)
    if tagged:
        return tagged

    for suffix, (category, link_category) in SUFFIXES.items():
        if text.endswith("_" + suffix):
            name = text[: -(len(suffix) + 1)]
            event_date = None
            # '2026_0121_大公演_渤海_お茶会' のように公演シート名が前置されていても許容
            dated = _parse_dated(name)
            if dated:
                perf = _split_performance(dated[1])
                if perf:
                    event_date, name = dated[0], perf[1]
                else:  # '2026_0125_雨にじむ渤海_親睦会' のように、種別なしで日付が前置されている場合
                    event_date, name = dated[0], dated[1]
            if not name:
                return SheetInfo(sheet_name, UNKNOWN, "", error="イベント名が空です")
            return SheetInfo(sheet_name, category, name, event_date, link_category)

    dated = _parse_dated(text)
    if dated:
        event_date, rest, err = dated
        perf = _split_performance(rest)
        if perf:
            return SheetInfo(sheet_name, perf[0], perf[1], event_date, error=err)
        return SheetInfo(sheet_name, ANNUAL, rest, event_date, error=err)

    return SheetInfo(sheet_name, UNKNOWN, text, error="シート名が命名規則に一致しません")
