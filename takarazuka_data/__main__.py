"""使い方: python -m takarazuka_data [入力フォルダ] [-o 出力フォルダ]"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .classify import classify_sheet
from .columns import is_blank, map_header
from .columns import load_aliases
from .identity import absorb_review_decisions, save_master
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
    ap.add_argument("--master", default="data/master", help="顧客マスターの保存先")
    ap.add_argument("--inspect", action="store_true", help="シート名と列名だけを表示（中身は表示しない）")
    args = ap.parse_args(argv)

    src = Path(args.input)
    if not src.exists():
        src.mkdir(parents=True)
        raise SystemExit(f"{src} フォルダを作りました。ここに Excel/CSV を入れてもう一度実行してください")
    paths = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv") and not p.name.startswith("~$"))
    if not paths:
        raise SystemExit(f"{src} に Excel/CSV ファイルがありません")

    load_aliases("config/column_aliases.csv")
    if args.inspect:
        inspect(paths)
        return
    master_dir, out_dir = Path(args.master), Path(args.output)
    absorbed = absorb_review_decisions(out_dir / "match_review.csv", master_dir)
    if absorbed:
        print(f"前回の確認結果（同一/別人）を {absorbed} 件取り込みました")
    result = run(paths, Path(args.links), Path(args.prices), master_dir)
    save_master(result.master, master_dir)
    written = write_outputs(result, out_dir)

    # 個人情報は表示せず件数のみ
    print(f"ファイル: {len(paths)} / イベント: {len(result.events)} / 人物: {len(result.persons)}")
    print(f"今回の申請: {len(result.application_requests)} 件")
    print(f"顧客マスター: {(result.master['merged_into'] == '').sum()} 人（{master_dir}）")
    if len(result.match_review):
        print(f"★ 同一人物か確認が必要な組: {len(result.match_review)} 件 → {out_dir / 'match_review.csv'} の"
              " decision 列に「同一」か「別人」を書いて保存し、もう一度実行してください")
        for reason, n in result.match_review["reason"].value_counts().items():
            print(f"    内訳: {reason}: {n} 件")
    for cat, n in result.events["category"].value_counts().items():
        print(f"  {cat}: {n}")
    levels = Counter(i["level"] for i in result.issues)
    if levels:
        print("要確認: " + ", ".join(f"{k}={v}" for k, v in levels.items()) + " → review.csv を確認してください")
    errors = [i for i in result.issues if i["level"] == "error"]
    for i in errors[:20]:  # エラーの内容（個人情報は含まない）
        print(f"  ✗ {i['sheet']}: {i['message']}")
    for p in written:
        print(f"出力: {p}")


if __name__ == "__main__":
    main()
