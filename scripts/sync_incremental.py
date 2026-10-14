#!/usr/bin/env python3
"""增量同步：把已下载的海报 + checkpoint 数据同步进 website/，供预览。
可反复运行（只拷新增，不重拷已有），采集过程中随时可刷新网站。

用法：
  python scripts/sync_incremental.py
说明：
  - 数据源优先 downloads/data/wallpapers.json（全量采完会生成）；
    没生成时退回用 downloads/checkpoint/homeView.jsonl 里已采的条目。
  - 海报：只拷 downloads/posters/ 里**已存在**的，缺失的保持不拷（前端回退远端 URL）。
  - 不碰正在写入的 checkpoint，纯只读 + 复制。
"""
import json, shutil, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CKPT = ROOT / "downloads" / "checkpoint" / "homeView.jsonl"
DATA = ROOT / "downloads" / "data" / "wallpapers.json"
DST_API = ROOT / "website" / "api"
DST_POSTERS = ROOT / "website" / "posters"


def load_items():
    """优先 checkpoint（边采边存，随时可用）；checkpoint 缺失时退回全量 JSON。"""
    items = []
    if CKPT.exists():
        for line in CKPT.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                it = json.loads(line)
            except Exception:
                continue
            it.pop("_page", None)
            it.setdefault("source", "homeView")
            items.append(it)
        seen, dedup = set(), []
        for it in items:
            key = it.get("video") or it.get("poster")
            if key and key not in seen:
                seen.add(key)
                dedup.append(it)
        print(f">>> 数据源：checkpoint（{len(dedup)} 条，去重后）")
        return dedup
    if DATA.exists():
        d = json.loads(DATA.read_text(encoding="utf-8"))
        for it in d:
            it.setdefault("source", "homeView")
        print(f">>> 数据源：{DATA.name}（{len(d)} 条）")
        return d
    sys.exit("未找到数据源：downloads/checkpoint/homeView.jsonl 或 downloads/data/wallpapers.json")


def poster_local_rel(it):
    """与 scrape.py 的 poster_dest() 对齐，返回本地海报相对 ROOT 的路径。"""
    import re
    source = it.get("source", "homeView")
    def _safe_prefix(title):
        s = re.sub(r'[\\/:*?"<>|]', '_', title or "")
        s = re.sub(r'\s+', ' ', s).strip()
        return s[:30]
    safe = _safe_prefix(it.get("title", "")) + "_" + os.path.basename(it.get("poster", ""))
    return f"posters/{source}/{safe}"


def main():
    items = load_items()

    DST_API.mkdir(parents=True, exist_ok=True)
    DST_API.joinpath("wallpapers.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f">>> 数据 {len(items)} 条 -> website/api/wallpapers.json")

    # 只拷已下载的海报（文件名与 scrape.py 的 poster_dest() 对齐）
    copied, skipped = 0, 0
    seen_rel = set()
    for it in items:
        rel = poster_local_rel(it)
        if rel in seen_rel:
            continue
        seen_rel.add(rel)
        src = ROOT / rel
        if not src.exists():
            skipped += 1
            continue
        dst = ROOT / "website" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            continue
        shutil.copy2(src, dst)
        copied += 1
    print(f">>> 海报已拷 {copied} 张（新增），{skipped} 张未下载（前端回退远端 URL）")
    print("完成：刷新 http://127.0.0.1:8091/ 查看最新")


if __name__ == "__main__":
    main()
