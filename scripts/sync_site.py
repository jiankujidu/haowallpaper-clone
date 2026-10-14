#!/usr/bin/env python3
"""把采集出的数据 + 海报图 同步进 clone 网站前端。
用法：
  python scripts/sync_site.py                # 同步全量
  python scripts/sync_site.py --sample 60    # 只放前 60 条做演示（全量 5.7 万条时推荐）
同步内容：
  1. downloads/data/wallpapers.json -> website/api/wallpapers.json
  2. downloads/posters/<source>/<file> -> website/posters/<source>/<file>
说明：
  - 前端 app.js 读 /api/wallpapers.json，并用 每张图 的 poster(远端URL)+source 定位
    本地海报 website/posters/<source>/<basename>。这里保证该目录与 basename 对齐。
  - 本地 posters 目录是可选加速项：若缺失，前端自动回退到远端 URL，网站仍能正常显示。
"""
import argparse, json, shutil, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DATA = ROOT / "downloads" / "data" / "wallpapers.json"
DST_API = ROOT / "website" / "api"
DST_POSTERS = ROOT / "website" / "posters"


def sync_posters(data, copied_set):
    """把 downloads/posters 下对应的海报拷到 website/posters（保持 <source>/<file> 结构）。"""
    copied = 0
    for it in data:
        source = it.get("source", "homeView")
        base = os.path.basename(it.get("poster", ""))
        if not base:
            continue
        rel = f"{source}/{base}"
        if rel in copied_set:
            continue
        src = ROOT / "downloads" / "posters" / rel
        if not src.exists():
            continue
        dst = DST_POSTERS / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied_set.add(rel)
        copied += 1
    return copied


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="只取前 N 条（0=全量）")
    args = ap.parse_args()

    if not SRC_DATA.exists():
        sys.exit(f"未找到 {SRC_DATA}，请先运行 scripts/scrape.py")

    data = json.loads(SRC_DATA.read_text(encoding="utf-8"))
    if args.sample:
        data = data[: args.sample]

    DST_API.mkdir(parents=True, exist_ok=True)
    DST_API.joinpath("wallpapers.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f">>> 同步数据 {len(data)} 条 -> website/api/wallpapers.json")

    copied = sync_posters(data, set())
    print(f">>> 同步海报 {copied} 张 -> website/posters/  (缺失的回退远端 URL)")
    print("完成：刷新 http://127.0.0.1:8091/ 即可看到最新数据")


if __name__ == "__main__":
    main()
