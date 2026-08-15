#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""道路グラフの実物を「リリース添付ファイル」として出せる形に並べる。

【なぜ引っ越すか（2026-08-15）】
GitHub Pages は**公開サイト全体で1GBまで**。37営業圏で 0.997GB と上限に張り付き、
83営業圏では約2.2GB になって入らないことが分かった。上限を超えると
「大きいファイルだけ弾かれる」のではなく**サイトごと公開が止まる**＝
今届いている営業圏もまとめて届かなくなる。

リリースの添付ファイルは 1ファイル2GiBまで・**総量も通信量も無制限**
（GitHub公式ドキュメントで確認）。目次(index.json)だけ Pages に残し、
実物は添付へ移す。目次の file は絶対URLになる
（アプリ側は sqlite_feed_updater.dart が http で始まれば直に取りに行く）。

【この道具がやること】
  _assets/<営業圏キー>_road_graph.sqlite.gz を作る（ハードリンク＝容量を食わない）
  添付ファイルはフォルダを持てないので、平らで一意な名前に直す必要がある。

使い方:
    python3 tools/stage_release_assets.py            # 並べる
    python3 tools/stage_release_assets.py --print-cmd # 社長が打つコマンドを出す
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "_assets")
REPO = "taxilog-app/route_roadgraph_feed"


def asset_name(key):
    return f"{key}_road_graph.sqlite.gz"


def release_url(tag, key):
    return f"https://github.com/{REPO}/releases/download/{tag}/{asset_name(key)}"


def main():
    idx = json.load(open(os.path.join(HERE, "index.json"), encoding="utf-8"))
    tag = "data-" + idx["dataMonth"]
    os.makedirs(ASSETS, exist_ok=True)

    staged, missing, total = [], [], 0
    for a in idx["areas"]:
        key = a["key"]
        src = os.path.join(HERE, key, "road_graph.sqlite.gz")
        if not os.path.exists(src):
            missing.append(key)
            continue
        dst = os.path.join(ASSETS, asset_name(key))
        if os.path.exists(dst):
            os.remove(dst)
        os.link(src, dst)            # ハードリンク＝実体は1つ（1GBを二重に持たない）
        staged.append(dst)
        total += os.path.getsize(dst)

    if "--print-cmd" in sys.argv:
        print(f"gh release create {tag} \\")
        print(f"  --repo {REPO} \\")
        print(f"  --title '道路グラフ {idx['dataMonth']}' \\")
        print(f"  --notes '営業圏ごとの道路グラフ（交差点＋道路区間）。"
              f"目次は https://taxilog-app.github.io/route_roadgraph_feed/index.json'  \\")
        print(f"  {os.path.join(HERE, '_assets')}/*.gz")
        return

    print(f"並べました: {len(staged)}件 / 合計 {total / 2**30:.2f}GB → {ASSETS}")
    if missing:
        print(f"⚠️ 実物が無い営業圏: {missing}")
    print()
    print("次にやること（🔴 社長が実行＝PCの外へ出す作業）:")
    print(f"  1. リリースを作って添付する")
    print(f"     python3 tools/stage_release_assets.py --print-cmd  で出るコマンド")
    print(f"  2. 目次を絶対URLに書き換える（Claudeがやる）")
    print(f"     python3 tools/switch_index_to_release.py {tag}")
    print(f"  3. 実物を置き場から外す（履歴には残るが、公開サイトからは消える）")
    print(f"  4. 検査 → push")


if __name__ == "__main__":
    main()
