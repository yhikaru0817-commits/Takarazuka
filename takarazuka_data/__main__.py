"""使い方: python -m takarazuka_data [入力フォルダ] [-o 出力フォルダ]"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .pipeline import run, write_outputs


def main(argv=None):
    ap = argparse.ArgumentParser(description="ファンクラブ管理データを整形します（ネット通信なし）")
    ap.add_argument("input", nargs="?", default="data/raw", help="Excel/CSV を置いたフォルダ")
    ap.add_argument("-o", "--output", default="output", help="出力フォルダ")
    ap.add_argument("--links", default="config/event_links.csv", help="お茶会・親睦会の紐づけ指定")
    args = ap.parse_args(argv)

    src = Path(args.input)
    paths = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv") and not p.name.startswith("~$"))
    if not paths:
        raise SystemExit(f"{src} に Excel/CSV ファイルがありません")

    result = run(paths, Path(args.links))
    written = write_outputs(result, Path(args.output))

    # 個人情報は表示せず件数のみ
    print(f"ファイル: {len(paths)} / イベント: {len(result.events)} / 人物: {len(result.persons)}")
    for cat, n in result.events["category"].value_counts().items():
        print(f"  {cat}: {n}")
    levels = Counter(i["level"] for i in result.issues)
    if levels:
        print("要確認: " + ", ".join(f"{k}={v}" for k, v in levels.items()) + " → review.csv を確認してください")
    for p in written:
        print(f"出力: {p}")


if __name__ == "__main__":
    main()
