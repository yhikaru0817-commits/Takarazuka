"""使い方: python -m takarazuka_data [入力フォルダ] [-o 出力フォルダ]"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .classify import classify_sheet
from .columns import is_blank, map_header
from .pipeline import find_header, read_sheets, run, write_outputs


def inspect(paths):
    """シート名と列名だけを表示する（データの中身は表示しない）。共有して相談するとき用。"""
    for sheet_name, df, file_name in read_sheets(paths):
        info = classify_sheet(sheet_name)
        print(f"\n[{file_name}] {sheet_name} → {info.category}" + (f"（{info.error}）" if info.error else ""))
        header_row, _ = find_header(df)
        if header_row is None:
            print("  ヘッダ行を判定できません（中身は表示しません）")
            continue
        print(f"  ヘッダ: {header_row + 1} 行目 / データ行数: {len(df) - header_row - 1}")
        for h in df.iloc[header_row]:
            if not is_blank(h):
                print(f"  - {h} → {map_header(h) or '（未対応）'}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="ファンクラブ管理データを整形します（ネット通信なし）")
    ap.add_argument("input", nargs="?", default="data/raw", help="Excel/CSV を置いたフォルダ")
    ap.add_argument("-o", "--output", default="output", help="出力フォルダ")
    ap.add_argument("--links", default="config/event_links.csv", help="お茶会・親睦会の紐づけ指定")
    ap.add_argument("--prices", default="config/seat_prices.csv", help="席種ごとのチケット価格")
    ap.add_argument("--inspect", action="store_true", help="シート名と列名だけを表示（中身は表示しない）")
    args = ap.parse_args(argv)

    src = Path(args.input)
    paths = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv") and not p.name.startswith("~$"))
    if not paths:
        raise SystemExit(f"{src} に Excel/CSV ファイルがありません")

    if args.inspect:
        inspect(paths)
        return
    result = run(paths, Path(args.links), Path(args.prices))
    written = write_outputs(result, Path(args.output))

    # 個人情報は表示せず件数のみ
    print(f"ファイル: {len(paths)} / イベント: {len(result.events)} / 人物: {len(result.persons)}")
    print(f"今回の申請: {len(result.application_requests)} 件")
    for cat, n in result.events["category"].value_counts().items():
        print(f"  {cat}: {n}")
    levels = Counter(i["level"] for i in result.issues)
    if levels:
        print("要確認: " + ", ".join(f"{k}={v}" for k, v in levels.items()) + " → review.csv を確認してください")
    for p in written:
        print(f"出力: {p}")


if __name__ == "__main__":
    main()
