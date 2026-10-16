#!/usr/bin/env python3
"""
补采：对 checkpoint 里 ok=true 但缺 colorTone 的 wtId 重新抓一次，
把完整记录（含 colorTone）追加到 downloads/checkpoint/details.jsonl。
后续行覆盖前一行（合并脚本按最后出现的记录为准）。

用法：
  python scripts/scrape_details_fix.py --workers 12
"""
import argparse, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DETAILS = ROOT / "downloads" / "checkpoint" / "details.jsonl"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

import re


def http_get(url, timeout=25):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://haowallpaper.com/"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return None


def parse_detail_html(html):
    out = {"ok": False, "category": "", "tags": [], "width": 0, "height": 0,
           "fileSize": "", "creator": "", "publishDate": "", "downloadCount": 0,
           "mediaType": "", "previewUrl": "", "fullTitle": "", "colorTone": ""}
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        block = block.strip()
        if not block:
            continue
        try:
            obj = json.loads(block)
        except Exception:
            continue
        if obj.get("contentUrl"):
            out["ok"] = True
            out["fullTitle"] = obj.get("name", "")
            out["width"] = int(obj.get("width") or 0)
            out["height"] = int(obj.get("height") or 0)
            out["fileSize"] = obj.get("contentSize") or ""
            out["creator"] = (obj.get("creator") or {}).get("name", "")
            out["publishDate"] = obj.get("uploadDate") or ""
            stat = obj.get("interactionStatistic") or {}
            out["downloadCount"] = int(stat.get("userInteractionCount") or 0)
            out["mediaType"] = "video" if obj.get("@type") == "VideoObject" else "image"
            out["previewUrl"] = obj.get("contentUrl") or ""
            desc = obj.get("description") or ""
            m = re.search(r"所属分类：([^，、]+)、", desc)
            if m:
                out["category"] = m.group(1)
            m = re.search(r"色系：([^，、]+)、", desc)
            if m:
                out["colorTone"] = m.group(1)
            m = re.search(r"【([^】]+)】", desc)
            if m:
                out["tags"] = [t for t in m.group(1).split("、") if t][:15]
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    # 收集缺 colorTone 的 wtId（按最后出现的记录为准）
    last = {}
    for line in open(DETAILS, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("ok") and rec.get("wtId"):
            last[str(rec["wtId"])] = rec
    todo = [w for w, r in last.items() if not r.get("colorTone")]
    print(f"需补采: {len(todo)}")
    if not todo:
        return

    import threading
    write_guard = threading.Lock()
    ok_count = 0

    def do_one(wtId):
        nonlocal ok_count
        html = http_get(f"https://haowallpaper.com/homeViewLook/{wtId}")
        if not html:
            return
        rec = parse_detail_html(html)
        rec["wtId"] = wtId
        if rec.get("ok") and rec.get("colorTone"):
            with write_guard:
                with open(DETAILS, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ok_count += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(do_one, w) for w in todo]
        done = 0
        for _ in as_completed(futs):
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(todo)} 补全 {ok_count}  速率={done/(time.time()-t0):.1f}/s")

    print(f"完成: 补全 {ok_count}/{len(todo)}，用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
