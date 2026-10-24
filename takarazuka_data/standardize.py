"""既存のバラバラなシートを、決められた形式（シート名・列順）に整形する。ローカル専用。

流れ:
    1. data/original/ の全シートについて、種別・日付・名前を推測して data/sheet_map.csv に書く
       （すでに書かれている行は人の修正を優先して残す）
    2. sheet_map.csv の内容に従って、各シートを標準の列に揃えて data/raw/<標準シート名>.csv に出力
       （確認用に data/standardized.xlsx にもまとめる）
    3. その後 python -m takarazuka_data で顧客マスター作成・統合を行う

使い方: python -m takarazuka_data.standardize [元フォルダ] [-o 出力フォルダ] [--map sheet_map.csv]
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .classify import (
    ANNUAL, GOODS, LARGE, ROSTER, SMALL, SOCIAL, TEA_PARTY, UNKNOWN, classify_sheet, normalize_text,
)
from .columns import (
    AMOUNT_FIELDS, EXPECTED_AMOUNTS, PERSON_FIELDS, clean_amount, is_blank, load_aliases, map_header,
)
from .pipeline import _is_total_row, find_header, normalize_row, read_sheets

CATEGORIES = [LARGE, SMALL, TEA_PARTY, SOCIAL, ANNUAL, GOODS, ROSTER, "skip"]
CATEGORY_LABEL = {LARGE: "大公演", SMALL: "小公演"}
SUFFIX_LABEL = {TEA_PARTY: "お茶会", SOCIAL: "親睦会", GOODS: "グッズ", ROSTER: "名簿"}
MAP_COLUMNS = ["source_file", "source_sheet", "category", "date", "name", "target_sheet", "rows", "note"]

# 指定の列名と順番
OUTPUT_HEADERS = {
    "name_kanji": "name(漢字)", "name_kana": "name katakana", "family_name": "Family name",
    "first_name": "First name", "email": "mail", "phone": "phone-number", "postal_code": "post-number",
    "prefecture": "prefecture", "address1": "address 1", "address2": "address 2",
    "ticket": "Ticket", "support": "Support", "entry_fee": "Entry_fee", "total_cost": "total_cost",
}
OPTIONAL_HEADERS = {"line_id": "LINE ID", "seat_type": "席種", "quantity": "枚数"}  # 元にあれば残す
BASE_FIELDS = [f for f in PERSON_FIELDS if f != "line_id"]

# 種別の推測に使う語（シート名・ファイル名から）
_GUESS_WORDS = [
    (TEA_PARTY, ["お茶会", "茶会"]),
    (SOCIAL, ["親睦会"]),
    (GOODS, ["グッズ", "goods"]),
    (LARGE, ["大公演", "大劇場", "宝塚大劇場", "東京宝塚劇場", "本公演", "large"]),
    (SMALL, ["小公演", "別箱", "小劇場", "バウ", "梅田", "ドラマシティ", "全国ツアー", "博多座", "御園座",
             "KAAT", "赤坂", "東京建物", "small"]),
    (ROSTER, ["名簿", "住所録", "会員一覧", "会員リスト", "顧客リスト", "顧客一覧", "連絡先"]),  # 最後に判定
]
_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[年/.\-_ ](\d{1,2})[月/.\-_ ](\d{1,2})日?(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(20\d{2})[年/.\-_ ](\d{1,2})月?()(?!\d)"),  # 日がない
]


def guess(sheet_name: str, file_name: str, fields: set) -> dict:
    """シート名・ファイル名・列から 種別 / 日付 / 名前 を推測する。"""
    info = classify_sheet(sheet_name)
    if info.category != UNKNOWN and not info.error:  # すでに命名規則どおり
        return {"category": info.category, "date": info.event_date.strftime("%Y%m%d") if info.event_date else "",
                "name": info.name, "note": ""}

    text = normalize_text(sheet_name)
    both = text + " " + normalize_text(Path(file_name).stem)
    notes = []
    category = ""
    for cat, words in _GUESS_WORDS:
        if any(w.lower() in both.lower() for w in words):
            category = cat
            break
    if not category:  # 列から推測
        if "entry_fee" in fields:
            category = TEA_PARTY
        elif "ticket" in fields or "support" in fields:
            category = LARGE
            notes.append("大公演/小公演を確認")
        elif "total_cost" in fields:
            category = ANNUAL
            notes.append("種別を確認（年間企画と推測）")
        elif fields & {"email", "phone", "postal_code", "address1"}:
            category = ROSTER
            notes.append("金額の列がないため名簿と推測")
        else:
            notes.append("種別を記入してください")
    else:
        notes.append("推測")

    date = ""
    for src in (text, both):
        for pat in _DATE_PATTERNS:
            m = pat.search(src)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    date = f"{y:04d}{mo:02d}{d:02d}"
                    if not m.group(3):
                        notes.append("日が不明のため1日としました")
                    break
        if date:
            break
    if not date and category in (LARGE, SMALL, ANNUAL):
        notes.append("日付を記入してください")

    name = text
    for w in sorted((w for _, ws in _GUESS_WORDS for w in ws), key=len, reverse=True):  # 長い語から消す
        name = re.sub(re.escape(w), " ", name, flags=re.IGNORECASE)
    for pat in _DATE_PATTERNS:
        name = pat.sub(" ", name)
    name = re.sub(r"[_\s　()（）\[\]【】「」・\-]+", " ", name).strip()
    for w in ("申込み", "申込", "名簿", "一覧", "リスト", "参加者", "購入者", "チケット", "公演",
              "花組", "月組", "雪組", "星組", "宙組", "専科"):
        name = name.replace(w, " ")
    name = re.sub(r"\s+", " ", name).strip()
    if not name and category == ROSTER:
        name = "会員"
    if not name:
        notes.append("名前を記入してください")
    return {"category": category, "date": date, "name": name, "note": "・".join(notes)}


def target_sheet(category: str, date: str, name: str) -> str:
    """標準のシート名を作る。必要な項目が欠けていれば空文字。"""
    name = normalize_text(name).replace("_", " ")
    if category in (LARGE, SMALL):
        return f"{date[:4]}_{date[4:8]}_{CATEGORY_LABEL[category]}_{name}" if len(date) == 8 and name else ""
    if category in SUFFIX_LABEL:
        return f"{name}_{SUFFIX_LABEL[category]}" if name else ""
    if category == ANNUAL:
        return f"{date[:4]}_{date[4:8]}_{name}" if len(date) == 8 and name else ""
    return ""


def load_map(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=MAP_COLUMNS)
    for enc in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("").reindex(columns=MAP_COLUMNS, fill_value="")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判定できません: {path.name}")


def standardize_sheet(df: pd.DataFrame, category: str, issue) -> tuple[pd.DataFrame | None, list[str]]:
    """1シートを標準の列に揃える。戻り値: (整形後の表, 未対応の列名)"""
    header_row, mapping = find_header(df)
    if header_row is None:
        issue("ヘッダ行が見つかりません（column_aliases.csv で列名を追加してください）")
        return None, []
    unmapped = [str(h) for c, h in df.iloc[header_row].items() if c not in mapping and not is_blank(h)]
    amounts = EXPECTED_AMOUNTS[category]
    found = set(mapping.values())
    for f in amounts:
        if f not in found:
            # 金額列が別名なら、他の金額列で代用（例: お茶会シートに「合計」しかない）
            alt = next((a for a in AMOUNT_FIELDS if a in found and a not in amounts), None)
            if alt and len(amounts) == 1:
                mapping = {c: (f if v == alt else v) for c, v in mapping.items()}
                issue(f"金額列 {alt} を {OUTPUT_HEADERS[f]} として扱いました")
            else:
                issue(f"金額列 {OUTPUT_HEADERS[f]} が見つかりません")
    optional = [f for f in OPTIONAL_HEADERS if f in set(mapping.values())] if category in (LARGE, SMALL) else \
        (["line_id"] if "line_id" in set(mapping.values()) else [])

    out = []
    for i in range(header_row + 1, len(df)):
        raw = {f: df.iat[i, df.columns.get_loc(c)] for c, f in mapping.items()}
        if all(is_blank(raw.get(f)) for f in PERSON_FIELDS) or _is_total_row(raw):
            continue
        rec = normalize_row(raw, lambda level, msg, r=i + 1: issue(f"{r}行目: {msg}"))
        if not rec["name_kanji"] and not rec["name_kana"]:
            issue(f"{i + 1}行目: 氏名がないため除外しました")
            continue
        row = {OUTPUT_HEADERS[f]: rec[f] for f in BASE_FIELDS}
        for f in amounts:
            row[OUTPUT_HEADERS[f]] = rec[f]
        for f in optional:
            v = raw.get(f)
            if f == "quantity":
                v = clean_amount(v)[0] if not is_blank(v) else ""
            elif f == "line_id":
                v = rec["line_id"]
            row[OPTIONAL_HEADERS[f]] = "" if is_blank(v) else normalize_text(v)
        out.append(row)
    cols = [OUTPUT_HEADERS[f] for f in BASE_FIELDS + amounts] + [OPTIONAL_HEADERS[f] for f in optional]
    return pd.DataFrame(out, columns=cols), unmapped


def main(argv=None):
    ap = argparse.ArgumentParser(description="既存のシートを決められた形式に整形します（ネット通信なし）")
    ap.add_argument("input", nargs="?", default="data/original", help="既存のシートを置いたフォルダ")
    ap.add_argument("-o", "--output", default="data/raw", help="整形後のCSVの出力先")
    ap.add_argument("--map", default="data/sheet_map.csv", help="シートの対応表")
    ap.add_argument("--aliases", default="config/column_aliases.csv", help="独自の列名の対応")
    args = ap.parse_args(argv)

    src, dst, map_path = Path(args.input), Path(args.output), Path(args.map)
    if not src.exists():
        src.mkdir(parents=True)
        raise SystemExit(f"{src} フォルダを作りました。既存のシート（Excel/CSV）をそのまま入れて、もう一度実行してください")
    n_alias = load_aliases(args.aliases)
    if n_alias:
        print(f"独自の列名を {n_alias} 件読み込みました")
    paths = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv") and not p.name.startswith("~$"))

    sheets = list(read_sheets(paths))
    smap = load_map(map_path)
    known = {(r["source_file"], r["source_sheet"]) for _, r in smap.iterrows()}
    added = []
    for sheet_name, df, file_name in sheets:
        if (file_name, str(sheet_name)) in known:
            continue
        _, mapping = find_header(df)
        g = guess(str(sheet_name), file_name, set(mapping.values()))
        added.append({"source_file": file_name, "source_sheet": str(sheet_name), **g})
    if added:
        smap = pd.concat([smap, pd.DataFrame(added)], ignore_index=True)
    smap["target_sheet"] = [target_sheet(c.strip(), re.sub(r"\D", "", d), n.strip())
                            for c, d, n in zip(smap["category"], smap["date"], smap["name"])]

    # 整形
    data = {(f, str(s)): df for s, df, f in sheets}
    report, merged = [], {}
    for idx, r in smap.iterrows():
        def issue(msg, r=r):
            report.append({"source_file": r["source_file"], "source_sheet": r["source_sheet"], "message": msg})
        cat = r["category"].strip()
        if cat == "skip":
            continue
        if (r["source_file"], r["source_sheet"]) not in data:
            issue("元のシートが見つかりません（sheet_map.csv の行を消して構いません）")
            continue
        if cat not in CATEGORIES or not r["target_sheet"]:
            issue("sheet_map.csv の category / date / name を記入してください（取り込まない場合は category に skip）")
            continue
        out, unmapped = standardize_sheet(data[(r["source_file"], r["source_sheet"])], cat, issue)
        if unmapped:
            issue("使わなかった列: " + ", ".join(unmapped) + "（必要なら column_aliases.csv に追加）")
        if out is None:
            continue
        smap.at[idx, "rows"] = str(len(out))
        merged.setdefault(r["target_sheet"], []).append(out)

    dst.mkdir(parents=True, exist_ok=True)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    smap.to_csv(map_path, index=False, encoding="utf-8-sig")
    view = map_path.parent / "standardized.xlsx"
    with pd.ExcelWriter(view) as w:
        for name, parts in sorted(merged.items()):
            df = pd.concat(parts, ignore_index=True)  # 同じ公演が複数シートに分かれていたら結合
            df.to_csv(dst / f"{name}.csv", index=False, encoding="utf-8-sig")
            title = unicodedata.normalize("NFKC", name)[:31]
            while title in w.sheets:  # Excel のシート名は31文字まで。重複したら番号を付ける
                title = title[:28] + f"~{len(w.sheets)}"
            df.to_excel(w, sheet_name=title, index=False)
        if not merged:
            pd.DataFrame().to_excel(w, sheet_name="empty")
    report_path = map_path.parent / "standardize_report.csv"
    pd.DataFrame(report, columns=["source_file", "source_sheet", "message"]).to_csv(
        report_path, index=False, encoding="utf-8-sig")

    # 個人情報は表示せず件数のみ
    todo = smap[(smap["category"] != "skip") & (smap["target_sheet"] == "")]
    guessed = smap[smap["note"].str.contains("推測|確認", na=False) & (smap["target_sheet"] != "")]
    print(f"元のシート: {len(sheets)} / 整形できたシート: {len(merged)}（{dst}/）")
    if added:
        print(f"新しく見つかったシート: {len(added)} 件を {map_path} に追加しました")
    if len(guessed):
        print(f"推測で分類したシート: {len(guessed)} 件 → {map_path} の category / date / name を確認してください")
    if len(todo):
        print(f"★ 記入が必要なシート: {len(todo)} 件 → {map_path} を開いて記入し、もう一度実行してください")
    if report:
        print(f"注意事項: {len(report)} 件 → {report_path}")
    print(f"確認用: {view}")
    return len(todo)


if __name__ == "__main__":
    main()
