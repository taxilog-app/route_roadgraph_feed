#!/usr/bin/env python3
"""道路グラフの目次(index.json)が、置いてある実物と本当に合うかを検査する。

【なぜこの道具が要るか】
  同じ間違いを2回やった。どちらも「アプリは落ちず・エラーも出ず・端末は毎回
  取りに行って静かに捨てる」という、気づく手がかりが無い壊れ方だった。

  1回目 2026-08-08: 目次に**袋(gz)の指紋**を書いた。当時のアプリは展開後で
        照合していたので弾かれ、福岡も東京も一度も端末に入らなかった。
  2回目 2026-08-09: 「展開後に直す」と判断して書き換えた。ところがその18時間前に
        アプリ側が**袋のまま照合**へ変わっていた（東京の展開後122MBをメモリに
        広げるとOOMで落ちるため）。向きが逆のまま、また入らない状態が続いた。

【この道具が守ること】
  ① 目次のsha256が、実物の**袋(gz)のまま**の指紋と一致するか
     🔴 道路グラフは「袋のまま」。交通規制フィードは「展開後」で**流儀が逆**。
        同じ会社の目次だからと揃えてはいけない（2回目の事故の原因がこれ）。
  ② bytes（配る大きさ）と bytesRaw（展開後）が実物と合っているか
     ＝運転手に見せる「受け取りますか？」の数字が嘘にならないように
  ③ ファイルが実在し、gzipとして展開でき、中身がSQLiteであること
  ④ 目次のschemaが、アプリが受け入れる版と一致しているか（人が目視する用に表示）

使い方:
    python3 tools/verify_index.py          # 手元のファイルで検査
    python3 tools/verify_index.py --remote # 公開中のURLから落として検査

🔴 **公開(push)の前に必ず通す。** 緑にならないものを外に出さない。
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(HERE, "index.json")
BASE_URL = "https://taxilog-app.github.io/route_roadgraph_feed"

# アプリ側の受け取り方（lib/services/sqlite_feed_updater.dart）。
# ここが変わったらこの道具も直すこと。
HASH_TARGET = "gz"  # "gz"=袋のまま / "raw"=展開後


def fetch(path, remote):
    if remote:
        with urllib.request.urlopen(f"{BASE_URL}/{path}", timeout=120) as r:
            return r.read()
    with open(os.path.join(HERE, path), "rb") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true",
                    help="公開中のURLから落として検査する")
    args = ap.parse_args()

    idx = json.loads(fetch("index.json", args.remote).decode("utf-8"))
    print(f"目次: {len(idx['areas'])}営業圏 / schema={idx.get('schema')} "
          f"/ dataMonth={idx.get('dataMonth')} "
          f"/ 指紋の流儀={HASH_TARGET}（gz=袋のまま）")

    ng = 0
    for a in idx["areas"]:
        key, path = a["key"], a["file"]
        try:
            raw = fetch(path, args.remote)
        except Exception as e:                       # noqa: BLE001
            print(f"  ❌ {key}: 実物が取れない {path} ({e})")
            ng += 1
            continue

        try:
            exp = gzip.decompress(raw) if path.endswith(".gz") else raw
        except Exception as e:                       # noqa: BLE001
            print(f"  ❌ {key}: gzipとして展開できない ({e})")
            ng += 1
            continue

        if not exp.startswith(b"SQLite format 3"):
            print(f"  ❌ {key}: 中身がSQLiteではない")
            ng += 1
            continue

        want = a.get("sha256")
        got = hashlib.sha256(raw if HASH_TARGET == "gz" else exp).hexdigest()
        other = hashlib.sha256(exp if HASH_TARGET == "gz" else raw).hexdigest()
        if want != got:
            ng += 1
            if want == other:
                # 2回やらかした間違いなので、名指しで出す
                print(f"  ❌ {key}: 指紋が**逆の流儀**（{'展開後' if HASH_TARGET=='gz' else '袋のまま'}）"
                      f"になっている。端末は落として捨て続ける。")
                print(f"      正しい値 = {got}")
            else:
                print(f"  ❌ {key}: 指紋が合わない\n"
                      f"      目次 = {want}\n      実物 = {got}")
        elif a.get("bytes") != len(raw) or a.get("bytesRaw") != len(exp):
            ng += 1
            print(f"  ❌ {key}: 大きさが目次と違う（運転手に出す数字が嘘になる）\n"
                  f"      目次 bytes={a.get('bytes')} bytesRaw={a.get('bytesRaw')}\n"
                  f"      実物 bytes={len(raw)} bytesRaw={len(exp)}")
        else:
            print(f"  ✅ {key}: 指紋・大きさとも一致 "
                  f"（配布 {len(raw)/1024/1024:.1f}MB → 展開後 {len(exp)/1024/1024:.1f}MB）")

    if ng:
        print(f"\n🔴 {ng}件がおかしい。**公開しないこと。**")
        return 1
    print("\n🟢 全部そろっています。公開して大丈夫です。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
