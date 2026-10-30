"""名寄せと顧客マスター（顧客番号の発行・維持）。

- 同一人物の判定: 名前（漢字 or カナ）＋ 連絡先（メール / 電話 / 郵便番号 / 住所 / LINE ID）のどれかが一致。
  家族で連絡先を共有するケースがあるため、連絡先だけでは結びつけない。
- 顧客番号 (C00001 …) は顧客マスター (data/master/customers.csv) に保存し、一度振ったら変えない。
- 機械で決められない組み合わせは match_review.csv に出し、人が「同一 / 別人」を書くと次回から反映する。
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from datetime import datetime
from itertools import combinations
from pathlib import Path

import pandas as pd

from .columns import PERSON_FIELDS, to_katakana

MASTER_FILE = "customers.csv"
DECISIONS_FILE = "match_decisions.csv"
MASTER_COLUMNS = ["customer_id"] + PERSON_FIELDS + ["first_seen", "last_seen", "merged_into", "note"]
MANUAL_FIELDS = {"note"}  # マスターで手入力する項目（データで上書きしない）
SAME, DIFFERENT = "同一", "別人"

# 異体字（髙/高 など）は同じ字として比べる
_VARIANTS = str.maketrans("髙﨑濵濱邊邉齋齊嶋澤櫻惠廣國德眞實壽瀨冨", "高崎浜浜辺辺斎斉島沢桜恵広国徳真実寿瀬富")


def person_name_key(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).translate(_VARIANTS)
    return re.sub(r"[\s・.\-_]", "", s).lower()


def kana_key(s: str) -> str:
    return person_name_key(to_katakana(unicodedata.normalize("NFKC", str(s))))


def address_key(prefecture: str, address1: str) -> str:
    """住所の表記ゆれ（丁目/番地/ハイフン/空白）を吸収した比較用キー。建物名は使わない。"""
    s = unicodedata.normalize("NFKC", f"{prefecture}{address1}")
    s = re.sub(r"[\s　]", "", s)
    s = re.sub(r"[‐‑‒–—―−ーｰ－]", "-", s)
    s = re.sub(r"(\d)(丁目|番地|番|号|の)", r"\1-", s)
    return s.strip("-").lower()


def contact_values(r) -> list[tuple[str, str]]:
    addr = address_key(r.get("prefecture", ""), r.get("address1", "")) if r.get("address1") else ""
    if not re.search(r"\d", addr) or len(addr) < 6:  # 番地まで書かれていない住所は照合に使わない
        addr = ""
    pairs = [("mail", r.get("email", "")), ("tel", r.get("phone", "")), ("zip", r.get("postal_code", "")),
             ("addr", addr), ("line", r.get("line_id", ""))]
    return [(t, v) for t, v in pairs if v]


def name_values(r) -> list[str]:
    out = []
    if r.get("name_kanji"):
        out.append("n:" + person_name_key(r["name_kanji"]))
    if r.get("name_kana"):
        out.append("k:" + kana_key(r["name_kana"]))
    return out


def identity_keys(r) -> list[str]:
    names, contacts = name_values(r), contact_values(r)
    keys = [f"{n}|{t}:{v}" for n in names for t, v in contacts]
    if not keys:  # 連絡先なし → 名前のみ（match_review で確認）
        keys = [f"{n}|-" for n in names]
    return keys


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


# ---------- ファイル入出力 ----------

def _read_csv(path: Path) -> pd.DataFrame:
    """Excel で保存し直した CSV（Shift_JIS）にも対応する。"""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判定できません: {path.name}")


def load_master(master_dir: Path | None) -> pd.DataFrame:
    if not master_dir or not (master_dir / MASTER_FILE).exists():
        return pd.DataFrame(columns=MASTER_COLUMNS)
    df = _read_csv(master_dir / MASTER_FILE)
    return df.reindex(columns=MASTER_COLUMNS, fill_value="")


def load_decisions(master_dir: Path | None) -> pd.DataFrame:
    cols = ["customer_id_a", "customer_id_b", "decision"]
    if not master_dir or not (master_dir / DECISIONS_FILE).exists():
        return pd.DataFrame(columns=cols)
    return _read_csv(master_dir / DECISIONS_FILE).reindex(columns=cols, fill_value="")


def absorb_review_decisions(review_path: Path, master_dir: Path) -> int:
    """前回の match_review.csv に書かれた判定を match_decisions.csv に取り込む。取り込んだ件数を返す。"""
    if not review_path.exists():
        return 0
    review = _read_csv(review_path)
    if "decision" not in review.columns:
        return 0
    review["decision"] = review["decision"].map(lambda s: unicodedata.normalize("NFKC", s).strip())
    review["decision"] = review["decision"].replace({"同じ": SAME, "同一人物": SAME, "違う": DIFFERENT, "別": DIFFERENT})
    filled = review[review["decision"].isin([SAME, DIFFERENT])][["customer_id_a", "customer_id_b", "decision"]]
    if filled.empty:
        return 0
    decisions = pd.concat([load_decisions(master_dir), filled]).drop_duplicates(
        ["customer_id_a", "customer_id_b"], keep="last")
    master_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(master_dir / DECISIONS_FILE, index=False, encoding="utf-8-sig")
    return len(filled)


def save_master(master: pd.DataFrame, master_dir: Path) -> Path:
    """上書き前に必ずバックアップを取る。"""
    master_dir.mkdir(parents=True, exist_ok=True)
    path = master_dir / MASTER_FILE
    if path.exists():
        backup = master_dir / "backup"
        backup.mkdir(exist_ok=True)
        shutil.copy2(path, backup / f"customers_{datetime.now():%Y%m%d_%H%M%S}.csv")
    master.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ---------- 顧客番号の割り当て ----------

def _next_number(ids) -> int:
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(r"C(\d+)", str(i)))]
    return max(nums, default=0) + 1


def assign_customer_ids(rows: pd.DataFrame, master: pd.DataFrame, decisions: pd.DataFrame, issue):
    """rows に customer_id を付け、更新後のマスターを返す。

    rows は effective_date 列を持つこと（新しい顧客番号を古い順に振るため）。
    """
    uf = _UnionFind()
    for _, m in master.iterrows():
        node = "M:" + m["customer_id"]
        uf.find(node)
        for k in identity_keys(m):
            uf.union(node, k)
        if m["merged_into"]:
            uf.union(node, "M:" + m["merged_into"])
    for _, d in decisions[decisions["decision"] == SAME].iterrows():
        uf.union("M:" + d["customer_id_a"], "M:" + d["customer_id_b"])

    row_root, name_only, named_nodes = [], [], {}
    for _, m in master.iterrows():
        if contact_values(m):
            for n in name_values(m):
                named_nodes.setdefault(n, []).append("M:" + m["customer_id"])
    for i, r in rows.iterrows():
        keys = identity_keys(r) or [f"R:{i}"]
        for k in keys[1:]:
            uf.union(keys[0], k)
        row_root.append(keys[0])
        if contact_values(r):
            for n in name_values(r):
                named_nodes.setdefault(n, []).append(keys[0])
        elif name_values(r):
            name_only.append((keys[0], name_values(r)))

    # 連絡先のない行（金額だけのシート等）は、同じ名前で連絡先のある人が1人だけなら自動で結びつける
    different = {frozenset((d["customer_id_a"], d["customer_id_b"]))
                 for _, d in decisions[decisions["decision"] == DIFFERENT].iterrows()}

    def master_ids(root):
        return {c for c in master["customer_id"] if uf.find("M:" + c) == root}

    linked = ambiguous = 0
    for key, names in name_only:
        roots = {uf.find(x) for n in names for x in named_nodes.get(n, [])}
        if len(roots) == 1:
            target = roots.pop()
            mine, theirs = master_ids(uf.find(key)), master_ids(target)
            if any(frozenset((a, b)) in different for a in mine for b in theirs):
                continue  # 「別人」と判定済み
            if uf.find(key) != target:
                uf.union(key, target)
                linked += 1
        elif len(roots) > 1:
            ambiguous += 1
    if linked:
        issue("info", f"連絡先のない {linked} 行を、同じ名前の人（1人だけ）に結びつけました")
    if ambiguous:
        issue("review", f"連絡先のない {ambiguous} 行は同じ名前の人が複数いるため結びつけていません（match_review.csv）")
    row_root = [uf.find(k) for k in row_root]

    active = set(master.loc[master["merged_into"] == "", "customer_id"])
    by_root: dict[str, list[str]] = {}
    for cid in master["customer_id"]:
        by_root.setdefault(uf.find("M:" + cid), []).append(cid)

    master = master.copy()
    root_to_id = {}
    for root, cids in by_root.items():
        live = sorted(c for c in cids if c in active) or sorted(cids)
        keep = live[0]
        root_to_id[root] = keep
        for other in live[1:]:
            if frozenset((keep, other)) in different:
                issue("error", f"{keep} と {other} は「別人」と判定済みですが、名前と連絡先が一致しています。"
                               "マスターを確認してください")
                continue
            master.loc[master["customer_id"] == other, "merged_into"] = keep
            issue("review", f"{other} を {keep} に統合しました（名前と連絡先が一致）")

    # 新しい顧客は初登場の古い順に番号を振る
    order = rows.assign(_root=row_root).sort_values(["effective_date", "source_row"], na_position="last")
    n = _next_number(master["customer_id"])
    for root in order["_root"]:
        if root not in root_to_id:
            root_to_id[root] = f"C{n:05d}"
            n += 1
    return pd.Series([root_to_id[r] for r in row_root], index=rows.index), master


def update_master(master: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """データから最新の連絡先をマスターに反映する（手入力項目は上書きしない）。"""
    records = {m["customer_id"]: dict(m) for m in master.to_dict("records")}
    latest_first = rows.sort_values("effective_date", ascending=False, na_position="last")
    latest = latest_first.replace("", pd.NA).groupby("customer_id")[PERSON_FIELDS].first()
    dated = rows.assign(d=rows["effective_date"].map(lambda d: "" if pd.isna(d) else str(d)))
    dated = dated[dated["d"] != ""]
    seen = dated.groupby("customer_id")["d"].agg(["min", "max"])
    for cid, vals in latest.iterrows():
        rec = records.setdefault(cid, {c: "" for c in MASTER_COLUMNS} | {"customer_id": cid})
        for f in PERSON_FIELDS:
            if f not in MANUAL_FIELDS and not pd.isna(vals[f]):
                rec[f] = vals[f]
        if cid in seen.index:
            lo, hi = seen.at[cid, "min"], seen.at[cid, "max"]
            if not rec["first_seen"] or lo < rec["first_seen"]:
                rec["first_seen"] = lo
            if hi > rec["last_seen"]:
                rec["last_seen"] = hi
    out = pd.DataFrame(list(records.values()), columns=MASTER_COLUMNS).fillna("")
    return out.sort_values("customer_id").reset_index(drop=True)


# ---------- 要確認の組み合わせ ----------

def review_candidates(rows: pd.DataFrame, master: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """自動では結びつけなかったが、同一人物かもしれない顧客の組を出す。"""
    cols = ["customer_id_a", "name_a", "kana_a", "customer_id_b", "name_b", "kana_b", "reason", "decision"]
    active = master[master["merged_into"] == ""]
    names: dict[str, set] = {}
    has_contact: set = set()
    index: dict[tuple, set] = {}
    for _, r in pd.concat([active, rows]).iterrows():
        cid = r["customer_id"]
        for n in name_values(r):
            names.setdefault(cid, set()).add(n)
            index.setdefault(("name", n), set()).add(cid)
        if contact_values(r):
            has_contact.add(cid)
        for t, v in contact_values(r):
            if t != "zip":  # 郵便番号だけの一致は多すぎるため対象外
                index.setdefault(("contact", f"{t}:{v}"), set()).add(cid)

    decided = {frozenset((d["customer_id_a"], d["customer_id_b"])) for _, d in decisions.iterrows()}
    reasons: dict[tuple, set] = {}
    labels = {"mail": "メール", "tel": "電話", "addr": "住所", "line": "LINE"}
    for (kind, value), cids in index.items():
        for a, b in combinations(sorted(cids), 2):
            if frozenset((a, b)) in decided:
                continue
            if kind == "name":
                both = a in has_contact and b in has_contact
                reasons.setdefault((a, b), set()).add(
                    "名前が同じで連絡先が違う" if both else "名前が同じ（連絡先のない方がいて、同名の人が複数）")
            elif not names.get(a, set()) & names.get(b, set()):
                reasons.setdefault((a, b), set()).add(f"{labels[value.split(':')[0]]}が同じで名前が違う")

    info = pd.concat([active, rows]).drop_duplicates("customer_id", keep="last").set_index("customer_id")
    out = [{"customer_id_a": a, "name_a": info.at[a, "name_kanji"], "kana_a": info.at[a, "name_kana"],
            "customer_id_b": b, "name_b": info.at[b, "name_kanji"], "kana_b": info.at[b, "name_kana"],
            "reason": "・".join(sorted(rs)), "decision": ""} for (a, b), rs in sorted(reasons.items())]
    return pd.DataFrame(out, columns=cols)
