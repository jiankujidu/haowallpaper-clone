#!/usr/bin/env python3
"""
把 details.jsonl 合并进 downloads/data/wallpapers.json，
并重新生成 api/wallpapers.json.gz（网站数据文件）。

新增/补全字段（来自详情页 JSON-LD）：
  fullTitle, category, subCategory, tags, width, height,
  fileSize, creator, publishDate, downloadCount, mediaType, previewUrl
  resolution / colorTone / size 等旧字段保留兼容，空值会被新字段覆盖。

用法：
  python scripts/merge_details.py            # 合并到 downloads/data/wallpapers.json + 重生成 api/*.gz
  python scripts/merge_details.py --check    # 只统计当前 details.jsonl 进度
"""
import argparse, gzip, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "downloads" / "data" / "wallpapers.json"
DETAILS = ROOT / "downloads" / "checkpoint" / "details.jsonl"
API_GZ = ROOT / "api" / "wallpapers.json.gz"


def load_details():
    """同一 wtId 出现多次时，取最后一次（补采记录追加在后面）。"""
    out = {}
    if not DETAILS.exists():
        return out
    with open(DETAILS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("ok") and rec.get("wtId"):
                out[str(rec["wtId"])] = rec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只打印进度，不写文件")
    args = ap.parse_args()

    details = load_details()
    print(f"details 已采: {len(details)}")

    if args.check:
        return

    t0 = time.time()
    with open(DATA, encoding="utf-8") as f:
        rows = json.load(f)
    print(f"wallpapers.json: {len(rows)} 条")

    hit = 0
    for row in rows:
        d = details.get(str(row.get("id")))
        if not d:
            continue
        hit += 1
        row["fullTitle"] = d.get("fullTitle") or row.get("title") or ""
        if d.get("category"):
            row["category"] = d["category"]
            sub = d["category"].split("｜")
            row["subCategory"] = sub[1] if len(sub) > 1 else ""
        if d.get("tags"):
            row["tags"] = d["tags"]
        if d.get("width"):
            row["width"] = d["width"]
            row["height"] = d.get("height") or 0
            row["resolution"] = f"{d['width']}x{row['height']}"
        if d.get("colorTone"):
            row["colorTone"] = d["colorTone"]
        if d.get("fileSize"):
            row["size"] = d["fileSize"]
        if d.get("creator"):
            row["creator"] = d["creator"]
        if d.get("publishDate"):
            row["publishDate"] = d["publishDate"]
        if d.get("downloadCount"):
            row["downloadCount"] = d["downloadCount"]
            row["downloads"] = d["downloadCount"]
        if d.get("mediaType"):
            row["mediaType"] = d["mediaType"]
        if d.get("previewUrl"):
            row["previewUrl"] = d["previewUrl"]

    print(f"命中 {hit}/{len(rows)}（{hit * 100 // len(rows)}%）")
    print(f"写入 {DATA} ...")
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    print(f"生成 {API_GZ} ...")
    API_GZ.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(API_GZ, "wb") as gz:
        gz.write(json.dumps(rows, ensure_ascii=False).encode("utf-8"))

    import os
    print(f"完成，用时 {time.time() - t0:.1f}s  (gz={os.path.getsize(API_GZ) // 1024} KB, "
          f"json={os.path.getsize(DATA) // 1024 // 1024} MB)")


if __name__ == "__main__":
    main()
