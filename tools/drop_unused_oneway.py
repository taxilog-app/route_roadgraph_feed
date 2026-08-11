#!/usr/bin/env python3
"""配信済みの道路グラフから、使っていない oneway_way / oneway_cell を落とす。

【なぜ】アプリのどこからも引いていない表が残っていた（2026-08-11 に確認）。
  東京では 6MB＋索引1MB＝配布物の約9%。ただの置き忘れ。
  生成道具（route_timer_app/tools/road_graph_build.py）は作らないように直したが、
  既に配信している福岡・東京はOSMから取り直さずにこの道具で作り直す
  （道の中身は1本も変えない＝取り直しの待ち時間もOverpassへの負荷もゼロ）。

【安全な理由】端末側の受け取り検査が要求するのは nodes / edges / edge_cell の3表だけ
  （road_graph_feed_updater.dart の sanityCheck）。この2表は要求されない。

使い方:
    python3 tools/drop_unused_oneway.py
    python3 tools/verify_index.py     # 🔴 必ずこれを通してから公開する
"""
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(HERE, "index.json")
DROP = ("oneway_cell", "oneway_way")


def main():
    idx = json.load(open(INDEX, encoding="utf-8"))
    for a in idx["areas"]:
        gz_path = os.path.join(HERE, a["file"])
        before_gz = os.path.getsize(gz_path)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "g.sqlite")
            with gzip.open(gz_path, "rb") as fi, open(db_path, "wb") as fo:
                shutil.copyfileobj(fi, fo)
            before_raw = os.path.getsize(db_path)

            con = sqlite3.connect(db_path)
            have = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            dropped = [t for t in DROP if t in have]
            for t in dropped:
                con.execute(f"DROP TABLE {t}")
            con.commit()
            con.execute("VACUUM")           # 消したぶんを実際に詰める
            # 消してはいけない物が残っているか、その場で確かめる
            left = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            need = {"nodes", "edges", "edge_cell"}
            if not need <= left:
                raise SystemExit(f"❌ {a['key']}: 必要な表が消えた {need - left}")

            after_raw = os.path.getsize(db_path)
            with open(db_path, "rb") as fi, \
                    gzip.open(gz_path, "wb", compresslevel=9) as fo:
                shutil.copyfileobj(fi, fo)
            after_gz = os.path.getsize(gz_path)
            raw_sha = hashlib.sha256(open(db_path, "rb").read()).hexdigest()

        # 🔴 目次の指紋は「袋(gz)のまま」（アプリが decompress:false で照合するため）
        a["sha256"] = hashlib.sha256(open(gz_path, "rb").read()).hexdigest()
        a["bytes"] = after_gz
        a["bytesRaw"] = after_raw
        print(f"{a['key']}: 落とした表={','.join(dropped) or 'なし'} / "
              f"展開後 {before_raw/1048576:.1f}→{after_raw/1048576:.1f}MB / "
              f"配布 {before_gz/1048576:.1f}→{after_gz/1048576:.1f}MB "
              f"({100*after_gz/before_gz:.0f}%)")
        assert raw_sha  # 展開後の指紋は使わない（袋のままが正）

    json.dump(idx, open(INDEX, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(INDEX, "a", encoding="utf-8").write("\n")
    print("index.json を書き換えました。🔴 tools/verify_index.py を通してから公開すること。")


if __name__ == "__main__":
    main()
