"""取り込み → 分類 → 正規化 → 名寄せ → 出力。

個人情報保護のため、このモジュールはネットワーク通信を一切行わず、
コンソールには件数のみを表示する（氏名等は出力ファイルにのみ書き出す）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .classify import (
    ANNUAL, APPLICATION, GOODS, LARGE, SMALL, SOCIAL, TEA_PARTY, UNKNOWN,
    SheetInfo, classify_sheet, name_key,
)
from .columns import (
    AMOUNT_FIELDS, EXPECTED_AMOUNTS, MULTI_FIELDS, PERSON_FIELDS, TICKET_FIELDS,
    clean_amount, clean_email, clean_kana, clean_phone, clean_postal, clean_prefecture,
    clean_quantity, clean_seat, clean_text, clean_time, is_blank, map_header, parse_show,
    split_alternatives, split_prefecture,
)

CATEGORY_PREFIX = {LARGE: "L", SMALL: "S", TEA_PARTY: "T", SOCIAL: "K", ANNUAL: "A", GOODS: "G", APPLICATION: "R"}
ACTUAL_CATEGORIES = [LARGE, SMALL, TEA_PARTY, SOCIAL, ANNUAL, GOODS]  # 実績（申請の見込額は含めない）
HEADER_SCAN_ROWS = 15


@dataclass
class Result:
    events: pd.DataFrame
    persons: pd.DataFrame
    spending: pd.DataFrame
    summary: pd.DataFrame
    ticket_history: pd.DataFrame
    application_requests: pd.DataFrame
    application_preferences: pd.DataFrame
    review: pd.DataFrame
    issues: list = field(default_factory=list)


# ---------- 読み込み ----------

def read_sheets(paths: list[Path]):
    """(シート名, ヘッダなし DataFrame, ファイル名) を返す。CSV はファイル名をシート名とする。"""
    for p in paths:
        suffix = p.suffix.lower()
        if suffix in (".xlsx", ".xlsm", ".xls"):
            for name, df in pd.read_excel(p, sheet_name=None, header=None, dtype=object).items():
                yield name, df, p.name
        elif suffix == ".csv":
            for enc in ("utf-8-sig", "cp932"):
                try:
                    df = pd.read_csv(p, header=None, dtype=object, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError(f"文字コードを判定できません: {p.name}")
            yield p.stem, df, p.name


def find_header(df: pd.DataFrame):
    """タイトル行などがあっても、列名に最も多く一致する行をヘッダとみなす。"""
    best_row, best_map = None, {}
    for i in range(min(HEADER_SCAN_ROWS, len(df))):
        mapping = {}
        for col, h in df.iloc[i].items():
            f = map_header(h)
            if f and (f in MULTI_FIELDS or f not in mapping.values()):
                mapping[col] = f
        if len(mapping) > len(best_map):
            best_row, best_map = i, mapping
    if len(set(best_map.values())) < 2:
        return None, {}
    return best_row, best_map


# ---------- 行の正規化 ----------

def normalize_row(raw: dict, issue) -> dict:
    rec = {
        "name_kanji": clean_text(raw.get("name_kanji")),
        "name_kana": clean_kana(raw.get("name_kana")),
        "family_name": clean_text(raw.get("family_name")),
        "first_name": clean_text(raw.get("first_name")),
        "email": clean_email(raw.get("email")),
        "prefecture": clean_prefecture(raw.get("prefecture")),
        "address1": clean_text(raw.get("address1")),
        "address2": clean_text(raw.get("address2")),
    }
    rec["phone"], err = clean_phone(raw.get("phone"))
    if err:
        issue("warning", err)
    rec["postal_code"], err = clean_postal(raw.get("postal_code"))
    if err:
        issue("warning", err)
    if not rec["name_kanji"] and (rec["family_name"] or rec["first_name"]):
        rec["name_kanji"] = f"{rec['family_name']} {rec['first_name']}".strip()
    if not rec["prefecture"] and rec["address1"]:
        rec["prefecture"], rec["address1"] = split_prefecture(rec["address1"])
    if rec["email"] and "@" not in rec["email"]:
        issue("warning", "メールアドレスの形式が不正です")
    for f in AMOUNT_FIELDS:
        rec[f], err = clean_amount(raw.get(f))
        if err:
            issue("error", f"{f}: {err}")
    return rec


def _is_total_row(raw: dict) -> bool:
    return any(str(raw.get(f, "")).strip() in ("合計", "計", "小計", "総計") for f in ("name_kanji", "name_kana"))


# ---------- 名寄せ ----------

class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _identity_keys(r) -> list[str]:
    """同一人物とみなすキー。家族で連絡先を共有するケースを考慮し、必ず名前と組み合わせる。"""
    names = [k for k in (name_key(r["name_kanji"]), name_key(r["name_kana"])) if k]
    contacts = [("mail", r["email"]), ("tel", r["phone"]), ("zip", r["postal_code"])]
    keys = [f"{n}|{t}:{v}" for n in names for t, v in contacts if v]
    if not keys:  # 連絡先なし → 名前のみで識別（要確認として報告）
        keys = [f"{n}|-" for n in names]
    return keys


def assign_person_ids(rows: pd.DataFrame) -> pd.Series:
    uf = _UnionFind()
    row_keys = []
    for _, r in rows.iterrows():
        keys = _identity_keys(r)
        for k in keys[1:]:
            uf.union(keys[0], k)
        row_keys.append(keys[0] if keys else None)
    roots = [uf.find(k) if k else None for k in row_keys]
    # クラスタ内の最小キーのハッシュを ID にする（個人情報は ID に含まれない）
    return pd.Series(
        ["P" + hashlib.sha256(k.encode()).hexdigest()[:10] if k else "" for k in roots],
        index=rows.index,
    )


# ---------- イベント紐づけ ----------

def load_link_overrides(path: Path | None) -> dict:
    """config/event_links.csv : fan_event_sheet,performance_sheet"""
    if not path or not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return {name_key(a): name_key(b) for a, b in zip(df["fan_event_sheet"], df["performance_sheet"]) if a and b}


def load_seat_prices(path: Path | None) -> dict:
    """config/seat_prices.csv : category,seat_type,price[,performance_sheet]

    performance_sheet を書いた行はその公演だけの価格として優先する。
    戻り値: {(category, seat_type, performance_sheet_key or ""): price}
    """
    if not path or not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    prices = {}
    for _, r in df.iterrows():
        amount, err = clean_amount(r["price"])
        if not err and r["category"] and r["seat_type"]:
            perf = name_key(r.get("performance_sheet", ""))
            prices[(r["category"].strip().lower(), r["seat_type"].strip().upper(), perf)] = amount
    return prices


def link_events(events: pd.DataFrame, overrides: dict, issue_for) -> pd.DataFrame:
    events = events.copy()
    events["linked_event_id"] = ""
    perfs = events[events["category"].isin([LARGE, SMALL])]
    by_sheet = {name_key(s): eid for s, eid in zip(perfs["sheet_name"], perfs["event_id"])}
    for idx, ev in events.iterrows():
        if ev["category"] not in (TEA_PARTY, SOCIAL, GOODS):
            continue
        issue = issue_for(ev["sheet_name"])
        override = overrides.get(name_key(ev["sheet_name"]))
        if override:
            if override in by_sheet:
                events.at[idx, "linked_event_id"] = by_sheet[override]
            else:
                issue("error", "event_links.csv の紐づけ先シートが見つかりません")
            continue
        targets = perfs if pd.isna(ev["link_category"]) else perfs[perfs["category"] == ev["link_category"]]
        key = name_key(ev["name"])
        cand = targets[targets["name"].map(name_key) == key]
        if not pd.isna(ev["event_date"]) and len(cand) > 1:
            cand = cand[cand["event_date"] == ev["event_date"]]
        if cand.empty:  # 部分一致（例: 「渤海 千秋楽」→「渤海」）
            cand = targets[targets["name"].map(lambda n: bool(name_key(n)) and (name_key(n) in key or key in name_key(n)))]
            if len(cand) == 1:
                issue("info", f"部分一致で紐づけました → {cand.iloc[0]['sheet_name']}")
        if len(cand) == 1:
            events.at[idx, "linked_event_id"] = cand.iloc[0]["event_id"]
        elif len(cand) > 1:
            latest = cand.sort_values("event_date").iloc[-1]
            events.at[idx, "linked_event_id"] = latest["event_id"]
            issue("warning", f"同名公演が複数あるため最新の {latest['sheet_name']} に紐づけました（event_links.csv で指定可）")
        else:
            want = {LARGE: "大公演", SMALL: "小公演"}.get(ev["link_category"], "公演")
            issue("warning", f"紐づく{want}が見つかりません（event_links.csv で指定してください）")
    return events


# ---------- メイン ----------

def _ticket_fields(raw: dict, info: SheetInfo, issue) -> dict:
    """公演（実績）・申請シートの席種 / 枚数 / 公演日時 / 振替を正規化する。"""
    perf_category = info.link_category if info.category == APPLICATION else info.category
    rec = {"seat_type": "", "quantity": pd.NA, "show_date": None, "show_time": "", "alternatives": []}
    if info.category == APPLICATION or not is_blank(raw.get("seat_type")):
        rec["seat_type"], err = clean_seat(raw.get("seat_type"), perf_category)
        if err:
            issue("warning", err)
    if info.category == APPLICATION or not is_blank(raw.get("quantity")):
        rec["quantity"], err = clean_quantity(raw.get("quantity"))
        if err:
            issue("warning" if rec["quantity"] else "error", err)
    rec["show_date"], t, date_err = parse_show(raw.get("show_date"), info.event_date)
    rec["show_time"] = clean_time(raw.get("show_time")) or t
    if date_err:
        issue("error", date_err)
    for alt in split_alternatives(raw.get("alt_dates", [])):
        d, t, err = parse_show(alt, info.event_date)
        if err:
            issue("error", f"振替日程: {err}")
        else:
            rec["alternatives"].append((d, t))
    if info.category == APPLICATION and rec["show_date"] is None and not date_err:
        issue("error", "第1希望の公演日がありません")
    return rec


def run(paths: list[Path], links_path: Path | None = None, prices_path: Path | None = None) -> Result:
    issues = []

    def issue_for(sheet, row=None):
        def add(level, msg):
            issues.append({"level": level, "sheet": sheet, "row": row, "message": msg})
        return add

    event_rows, data_rows, seen = [], [], set()
    for sheet_name, df, file_name in read_sheets(paths):
        info: SheetInfo = classify_sheet(sheet_name)
        sheet_issue = issue_for(sheet_name)
        if info.error:
            sheet_issue("error" if info.category == UNKNOWN else "warning", info.error)
        if info.category == UNKNOWN:
            continue
        if name_key(sheet_name) in seen:
            sheet_issue("error", "同名のシートが複数あります（2つ目以降はスキップ）")
            continue
        seen.add(name_key(sheet_name))

        event_id = f"{CATEGORY_PREFIX[info.category]}_{name_key(sheet_name)}"
        event_rows.append({
            "event_id": event_id, "category": info.category, "name": info.name,
            "event_date": info.event_date, "link_category": info.link_category,
            "sheet_name": sheet_name, "source_file": file_name,
        })

        header_row, mapping = find_header(df)
        if header_row is None:
            sheet_issue("error", "ヘッダ行が見つかりません")
            continue
        found = set(mapping.values())
        for f in EXPECTED_AMOUNTS[info.category]:
            if f not in found:
                sheet_issue("warning", f"金額列 {f} がありません")
        unmapped = [str(h) for c, h in df.iloc[header_row].items() if c not in mapping and not is_blank(h)]
        if unmapped:
            sheet_issue("info", f"未対応の列を無視しました: {', '.join(unmapped)}")

        for i in range(header_row + 1, len(df)):
            raw = {}
            for c, f in mapping.items():
                v = df.iat[i, df.columns.get_loc(c)]
                if f in MULTI_FIELDS:
                    raw.setdefault(f, []).append(v)
                else:
                    raw[f] = v
            if all(is_blank(raw.get(f)) for f in PERSON_FIELDS) or _is_total_row(raw):
                continue
            row_issue = issue_for(sheet_name, i + 1)  # Excel の行番号
            rec = normalize_row(raw, row_issue)
            if not rec["name_kanji"] and not rec["name_kana"]:
                row_issue("warning", "氏名がありません（名寄せ不可のためスキップ）")
                continue
            if info.category in (LARGE, SMALL, APPLICATION):
                rec.update(_ticket_fields(raw, info, row_issue))
            rec.update({"event_id": event_id, "source_row": i + 1})
            data_rows.append(rec)

    events = pd.DataFrame(event_rows, columns=[
        "event_id", "category", "name", "event_date", "link_category", "sheet_name", "source_file"])
    events = link_events(events, load_link_overrides(links_path), issue_for)
    # large / small はそれぞれ日付順の通し番号（直近 n 回の抽出に使う）
    events["seq"] = pd.NA
    for cat in (LARGE, SMALL, ANNUAL):
        mask = events["category"] == cat
        order = events[mask].sort_values("event_date", na_position="first").index
        events.loc[order, "seq"] = range(1, len(order) + 1)
    # ファンイベント・グッズの日付は紐づけ先の公演日付を引き継ぐ
    date_map = dict(zip(events["event_id"], events["event_date"]))
    events["effective_date"] = [
        d if not pd.isna(d) else date_map.get(l) for d, l in zip(events["event_date"], events["linked_event_id"])]
    events = events.sort_values(["effective_date", "category"], na_position="last")

    extra = ["seat_type", "quantity", "show_date", "show_time", "alternatives"]
    rows = pd.DataFrame(data_rows, columns=PERSON_FIELDS + AMOUNT_FIELDS + extra + ["event_id", "source_row"])
    rows["person_id"] = assign_person_ids(rows) if len(rows) else pd.Series(dtype=str)
    rows = rows.merge(events[["event_id", "category", "effective_date"]], on="event_id", how="left")
    applications = rows[rows["category"] == APPLICATION]
    actual = rows[rows["category"] != APPLICATION]

    # persons: 各項目について最新イベントの値を採用
    latest_first = rows.sort_values("effective_date", ascending=False, na_position="last")
    persons = (latest_first.replace("", pd.NA).groupby("person_id")[PERSON_FIELDS].first()
               .fillna("").reset_index())
    counts = actual.groupby("person_id")["event_id"].nunique().rename("event_count")
    persons = persons.merge(counts, on="person_id", how="left")
    persons["event_count"] = persons["event_count"].fillna(0).astype(int)
    persons["is_new"] = persons["event_count"] == 0  # 実績なし（今回の申請が初めて）

    # spending: 縦持ち（1行 = 人 × イベント × 費目）。実績のみ
    spending = actual.melt(
        id_vars=["person_id", "event_id", "category", "source_row"], value_vars=AMOUNT_FIELDS,
        var_name="item", value_name="amount")
    allowed = spending.apply(lambda r: r["item"] in EXPECTED_AMOUNTS[r["category"]], axis=1)
    stray = spending[~allowed & (spending["amount"] != 0)]
    for _, r in stray.iterrows():
        issue_for(events.set_index("event_id").at[r["event_id"], "sheet_name"], r["source_row"])(
            "warning", f"{r['category']} に想定外の金額列 {r['item']} があります（集計には含めます）")
    spending = spending[allowed | (spending["amount"] != 0)].drop(columns="source_row")

    # summary: 人 × 種別の合計金額（公演はチケット代とサポート代を分ける）
    key = spending["category"] + "_" + spending["item"]
    key = key.where(spending["category"].isin([LARGE, SMALL]), spending["category"])
    summary = spending.assign(key=key).pivot_table(index="person_id", columns="key", values="amount",
                                                   aggfunc="sum", fill_value=0)
    cols = ["large_ticket", "large_support", "small_ticket", "small_support", TEA_PARTY, SOCIAL, ANNUAL, GOODS]
    summary = summary.reindex(index=persons["person_id"], columns=cols, fill_value=0).fillna(0).astype(int)
    summary["support_total"] = summary["large_support"] + summary["small_support"]
    summary["total"] = summary[cols].sum(axis=1)
    summary = summary.reset_index().rename_axis(columns=None)

    # ticket_history: 過去公演の 1行 = 人 × 公演（席種・枚数は列があれば）
    ticket_history = actual[actual["category"].isin([LARGE, SMALL])][
        ["person_id", "event_id", "category", "seat_type", "quantity", "ticket", "support"]]

    # 今回の申請: requests (1行 = 1申請) と preferences (1行 = 第1希望 / 振替の各候補)
    prices = load_seat_prices(prices_path)
    perf_cat = dict(zip(events["event_id"], events["link_category"]))
    sheet_of = dict(zip(events["event_id"], events["sheet_name"]))
    req_rows, pref_rows = [], []
    for _, r in applications.iterrows():
        request_id = f"{r['event_id']}#{r['source_row']}"
        cat = perf_cat[r["event_id"]]
        price = prices.get((cat, r["seat_type"], name_key(sheet_of[r["event_id"]])),
                           prices.get((cat, r["seat_type"], "")))
        req_rows.append({
            "request_id": request_id, "event_id": r["event_id"], "performance_category": cat,
            "person_id": r["person_id"], "quantity": r["quantity"], "seat_type_requested": r["seat_type"],
            "support_expected": r["support"], "ticket_price": price,
            "ticket_amount": price * r["quantity"] if price is not None else None,
            "preference_count": (r["show_date"] is not None) + len(r["alternatives"]),
            "source_row": r["source_row"],
        })
        choices = ([(r["show_date"], r["show_time"])] if r["show_date"] is not None else []) + r["alternatives"]
        for rank, (d, t) in enumerate(choices, start=1):
            pref_rows.append({"request_id": request_id, "rank": rank, "is_alternative": rank > 1,
                              "show_date": d, "show_time": t})
    application_requests = pd.DataFrame(req_rows, columns=[
        "request_id", "event_id", "performance_category", "person_id", "quantity", "seat_type_requested",
        "support_expected", "ticket_price", "ticket_amount", "preference_count", "source_row"])
    application_preferences = pd.DataFrame(
        pref_rows, columns=["request_id", "rank", "is_alternative", "show_date", "show_time"])
    if len(applications) and not prices:
        issues.append({"level": "info", "sheet": "", "row": None,
                       "message": "config/seat_prices.csv がないためチケット代の見込みは空欄です"})

    # 同姓同名で連絡先が一致しない別IDを要確認として報告
    dup = persons.assign(k=persons["name_kanji"].map(name_key)).groupby("k")["person_id"].apply(list)
    for ids in dup[dup.map(len) > 1]:
        issues.append({"level": "review", "sheet": "", "row": None,
                       "message": f"同姓同名で連絡先が一致しない人物: {', '.join(ids)}（同一人物か確認してください）"})

    review = pd.DataFrame(issues, columns=["level", "sheet", "row", "message"])
    return Result(events, persons, spending, summary, ticket_history,
                  application_requests, application_preferences, review, issues)


def select_events(events: pd.DataFrame, n_large: int, n_small: int, n_annual: int = 1,
                  include_linked: bool = True) -> pd.DataFrame:
    """直近 n 回の large / small と直近の annual を抽出する（配分算出用）。

    include_linked=True のとき、選ばれた公演に紐づくお茶会・親睦会・グッズも含める。
    """
    picked = []
    for cat, n in ((LARGE, n_large), (SMALL, n_small), (ANNUAL, n_annual)):
        if n > 0:
            picked.append(events[events["category"] == cat].sort_values("seq").tail(n))
    base = pd.concat(picked) if picked else events.iloc[0:0]
    if include_linked:
        linked = events[events["linked_event_id"].isin(base["event_id"])]
        base = pd.concat([base, linked])
    return base


def write_outputs(result: Result, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "events": result.events, "persons": result.persons, "spending": result.spending,
        "summary": result.summary, "ticket_history": result.ticket_history,
        "application_requests": result.application_requests,
        "application_preferences": result.application_preferences, "review": result.review,
    }
    written = []
    for name, df in tables.items():
        p = out_dir / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")  # Excel で文字化けしないよう BOM 付き
        written.append(p)
    xlsx = out_dir / "formatted.xlsx"
    with pd.ExcelWriter(xlsx) as w:
        for name, df in tables.items():
            df.to_excel(w, sheet_name=name, index=False)
    written.append(xlsx)
    return written
