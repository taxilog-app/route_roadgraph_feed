#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""目次(index.json)の file を、リリース添付ファイルの絶対URLに書き換える。

🔴 **添付のアップロードが終わってから**実行すること。先に目次だけ書き換えると、
   運転手のアプリは「在るはずの物が404」で取得に失敗し続ける。

使い方:
    python3 tools/switch_index_to_release.py data-2026-08
    python3 tools/switch_index_to_release.py data-2026-08 --check  # 実物が在るか確かめるだけ
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "taxilog-app/route_roadgraph_feed"


def url_for(tag, key):
    return f"https://github.com/{REPO}/releases/download/{tag}/{key}_road_graph.sqlite.gz"


def exists(url):
    """添付が本当に置かれているか（転送を追って確かめる）。"""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200
    except Exception:                                    # noqa: BLE001
        return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    tag = sys.argv[1]
    check_only = "--check" in sys.argv
    p = os.path.join(HERE, "index.json")
    idx = json.load(open(p, encoding="utf-8"))

    ng = 0
    for a in idx["areas"]:
        u = url_for(tag, a["key"])
        ok = exists(u)
        print(f"  {'✅' if ok else '❌'} {a['key']}")
        if not ok:
            ng += 1
        elif not check_only:
            a["file"] = u

    if ng:
        print(f"\n🔴 {ng}件が添付されていない。アップロードを先に済ませること。"
              f"\n   目次は**書き換えていない**（中途半端な状態を作らない）。")
        sys.exit(1)

    if check_only:
        print("\n✅ 全部そろっている。--check を外して実行すると目次を書き換える。")
        return

    json.dump(idx, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(p, "a", encoding="utf-8").write("\n")
    print(f"\n✅ 目次の {len(idx['areas'])}件を {tag} の添付URLに向けた。"
          f"\n   次＝ tools/verify_index.py で検査 → 実物を git から外す → push")


if __name__ == "__main__":
    main()
