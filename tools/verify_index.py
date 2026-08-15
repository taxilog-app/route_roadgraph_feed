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
  ⑤ 中身が本当に入っているか（nodes/edges/edge_cell が0件でない・目次の件数と合う）
     🔴 2026-08-12 追加。生成道具から db.commit() が消え、**表はあるが1行も無い**
        69MBのファイルが出来た。SQLiteとしては正常・大きさも普通なので①〜④は
        全部すり抜ける。『それらしい物が出来ている』を根拠にしない。

使い方:
    python3 tools/verify_index.py          # 手元のファイルで検査
    python3 tools/verify_index.py --remote # 公開中のURLから落として検査

🔴 **公開(push)の前に必ず通す。** 緑にならないものを外に出さない。
"""
import argparse
import gzip
import sqlite3
import tempfile
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


# 目次のキー → 丁目境界の置き場の名前（**違う組だけ**書く）。
# アプリ側 lib/repositories/prefs_repository.dart の _feedAreaAlias の逆。
_KEY_TO_BOUNDARY = {
    "tokyo": "tokyo23",
    "kyoto": "kyoto_city",
    "saitama": "saitama_s",
}
_BOUNDARY_ROOT = os.path.expanduser("~/Developer/taxi関連/route_boundary_feed")


def _boundary_center(key):
    """その営業圏の実際の真ん中（緯度, 経度）。分からなければ None。"""
    d = _KEY_TO_BOUNDARY.get(key, key)
    path = os.path.join(_BOUNDARY_ROOT, d, "ward_frame.geojson")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            gj = json.load(f)
    except Exception:                                # noqa: BLE001
        return None
    la0 = lo0 = 1e9
    la1 = lo1 = -1e9
    for ft in gj.get("features", []):
        b = ft.get("properties", {}).get("b")        # [minLng,minLat,maxLng,maxLat]
        if not b:
            continue
        lo0, la0 = min(lo0, b[0]), min(la0, b[1])
        lo1, la1 = max(lo1, b[2]), max(la1, b[3])
    if la0 > la1:
        return None
    return ((la0 + la1) / 2, (lo0 + lo1) / 2)


def place_ng(key, bbox):
    """🔴 **キーは合っているが、中身が別の土地**を弾く（2026-08-13 追加）。

    実際にやらかした：広島市域の道路グラフを 'hiroshima' で公開した。
    ところが営業圏キーの正典ではその名前は**広島地区（呉・尾道・福山）**を指す。
    結果、その営業圏の運転手には範囲がまるごと違うデータが配られ、
    肝心の広島市域には何も届かない状態になった。
    指紋も大きさも件数も全部正しいので、ここまでの検査は全部すり抜ける。

    見方＝その営業圏の実際の真ん中が、目次の bbox の中に入っているか。
    （営業圏全体を覆えとは言わない。大阪のように「府の一部だけ配る」のは正しい）
    """
    c = _boundary_center(key)
    if c is None or not bbox or len(bbox) != 4:
        return None                                  # 照合できない＝黙って通す
    la, lo = c
    if bbox[0] <= la <= bbox[2] and bbox[1] <= lo <= bbox[3]:
        return None
    return (f"配っている場所が営業圏と違う（この営業圏の中心 "
            f"{la:.3f},{lo:.3f} が bbox {bbox} の外）。"
            f"キーの取り違えを疑うこと")


def counts_ng(exp, want):
    """展開したSQLiteの中身が空でないか・目次の件数と合うかを見る。

    おかしければ理由の文字列、問題なければ None を返す。
    端末側 road_graph_feed_updater.dart の sanityCheck と同じ3表を見る。"""
    tmp = os.path.join(tempfile.gettempdir(), "verify_road_graph.sqlite")
    try:
        with open(tmp, "wb") as f:
            f.write(exp)
        con = sqlite3.connect(tmp)
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"nodes", "edges", "edge_cell"}
        if not need <= have:
            return f"必要な表が無い（足りないもの: {sorted(need - have)}）"
        got = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in sorted(need)}
        con.close()
        empty = [t for t, v in got.items() if v == 0]
        if empty:
            return (f"表はあるが**中身が空**（0件: {', '.join(empty)}）。"
                    f"生成道具の db.commit() 抜けを疑うこと")
        for k, t in (("nodes", "nodes"), ("edges", "edges")):
            w = (want or {}).get(k)
            if w is not None and w != got[t]:
                return f"件数が目次と違う（{k}: 目次 {w:,} / 実物 {got[t]:,}）"
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fetch(path, remote):
    """目次の file を取ってくる。

    🔴 file は「相対」と「絶対URL」の両方がありうる（2026-08-15〜）。
       実物は GitHub Pages（**公開サイト全体で1GB**が上限）からリリース添付へ
       移した。移した営業圏は https://github.com/.../releases/download/... になる。
       手元で検査するときは、添付に出す前の実物 _assets/<名前> を見る
       （tools/stage_release_assets.py が並べる場所）。
    """
    if path.startswith("http"):
        if remote:
            with urllib.request.urlopen(path, timeout=300) as r:
                return r.read()
        name = path.rsplit("/", 1)[-1]
        with open(os.path.join(HERE, "_assets", name), "rb") as f:
            return f.read()
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
            # ⑤ 中身が本当に入っているか（表があるだけの空っぽを弾く）
            #    🔴 2026-08-12：生成道具から db.commit() が消えていて、**表はあるが
            #       1行も入っていない**69MBのファイルが出来た。SQLiteとしては正常で、
            #       大きさも普通なので、ここまでの検査は全部すり抜ける。
            #       端末側は空を弾くので入りはしないが、**気づく手がかりが無いまま
            #       「配信したのに誰にも届かない」**状態になる。数を見るまで信用しない。
            bad = counts_ng(exp, a.get("counts")) or place_ng(key, a.get("bbox"))
            if bad:
                ng += 1
                print(f"  ❌ {key}: {bad}")
                continue
            cn = a.get("counts") or {}
            print(f"  ✅ {key}: 指紋・大きさとも一致 "
                  f"（配布 {len(raw)/1024/1024:.1f}MB → 展開後 {len(exp)/1024/1024:.1f}MB"
                  f"・交差点 {cn.get('nodes', '?'):,} / 区間 {cn.get('edges', '?'):,}）")

    if ng:
        print(f"\n🔴 {ng}件がおかしい。**公開しないこと。**")
        return 1
    print("\n🟢 全部そろっています。公開して大丈夫です。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
