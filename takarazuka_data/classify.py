"""シート名からイベント種別を判定する。

命名規則:
    公演 (large/small) : year_date_種別_公演名    例) 2026_0121_大公演_渤海
    お茶会 (large 用)  : 公演名_お茶会
    親睦会 (small 用)  : 公演名_親睦会
    グッズ             : 公演名_グッズ
    annual             : year_date_企画名
    今回のチケット申請 : year_date_種別_公演名_申請   例) 2026_1105_大公演_星の詩_申請
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

LARGE = "large"
SMALL = "small"
TEA_PARTY = "tea_party"  # お茶会 (large に紐づく)
SOCIAL = "social"  # 親睦会 (small に紐づく)
ANNUAL = "annual"
GOODS = "goods"
APPLICATION = "application"  # 今回のチケット申請（実績ではなく見込み）
UNKNOWN = "unknown"

# 公演種別キーワード（比較は NFKC + 小文字化後）
LARGE_KEYWORDS = {"large", "大公演", "大劇場", "大劇場公演"}
SMALL_KEYWORDS = {"small", "小公演", "小劇場", "別箱", "別箱公演"}

APPLICATION_SUFFIXES = ("申請", "申込", "チケット申請")

# サフィックス → (種別, 紐づけ先の公演種別)
SUFFIXES = {
    "お茶会": (TEA_PARTY, LARGE),
    "親睦会": (SOCIAL, SMALL),
    "グッズ": (GOODS, None),  # large/small どちらでも可
}

_DATED = re.compile(r"^(\d{4})_(\d{4})_(.+)$")


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


def classify_sheet(sheet_name: str) -> SheetInfo:
    text = normalize_text(sheet_name)
    text = re.sub(r"\s*_\s*", "_", text)

    for suffix in APPLICATION_SUFFIXES:
        if text.endswith("_" + suffix):
            dated = _parse_dated(text[: -(len(suffix) + 1)])
            perf = _split_performance(dated[1]) if dated else None
            if not perf:
                return SheetInfo(sheet_name, UNKNOWN, text,
                                 error="申請シートは 年_月日_大公演/小公演_公演名_申請 の形式にしてください")
            # link_category に公演種別 (large/small) を持たせる
            return SheetInfo(sheet_name, APPLICATION, perf[1], dated[0], perf[0], error=dated[2])

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
