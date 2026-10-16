#!/usr/bin/env python3
"""
哲风壁纸 clone —— 详情页元数据采集（JSON-LD 版）
====================================================
背景：
  首轮采集（scrape.py）只拿到列表页 JSON-LD，category/tags/resolution 等字段全空，
  导致 clone 站点分类点击失效。本脚本遍历 downloads/data/wallpapers.json 的全部
  wtId，抓详情页 SSR 的 <script type="application/ld+json">（ImageObject / VideoObject），
  解析出：完整标题、分类、标签、宽高、文件大小、发布人、发布时间、下载量、媒体类型。

输出：
  downloads/checkpoint/details.jsonl  每行 {"wtId":..., "ok":true/false, 字段...}
  支持断点续传：已采过的 wtId 直接跳过。

用法：
  python scripts/scrape_details.py --limit 50 --workers 8     # 试跑 50 个
  python scripts/scrape_details.py --workers 12               # 全量后台跑
"""
import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "downloads" / "data" / "wallpapers.json"
CKPT = ROOT / "downloads" / "checkpoint" / "details.jsonl"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DETAIL_URL = "https://haowallpaper.com/homeViewLook/{wtid}"

# 文件锁（Windows 多进程保护）
try:
    import msvcrt
    HAVE_MSVCRT = True
except ImportError:
    HAVE_MSVCRT = False

import threading
_done = set()
_done_guard = threading.Lock()
_write_guard = threading.Lock()
_lock_file = None


def ensure_done_set():
    """从 checkpoint 加载已完成 id（只认 ok=true 的行）。"""
    global _lock_file
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    if not CKPT.exists():
        CKPT.touch()
    # 先读已完成的（旧记录，单进程读无竞争）
    with open(CKPT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("ok") and rec.get("wtId"):
                with _done_guard:
                    _done.add(str(rec["wtId"]))
    # 读完了再拿写锁（多进程场景，锁保留到进程结束）
    # Windows 的 msvcrt 锁是排他的，持有后再 open() 同文件会 Permission denied，
    # 所以用一个独立的 lock 文件承载锁。
    lock_path = CKPT.parent / "lock.details"
    if HAVE_MSVCRT:
        _lock_file = open(lock_path, "a")
        try:
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("另一进程正持有 checkpoint 锁，退出", file=sys.stderr)
            sys.exit(1)


def http_get(url, timeout=25, retries=2):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://haowallpaper.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            if i == retries - 1:
                return None
            time.sleep(0.5 + i)
    return None


def parse_detail_html(html):
    """解析详情页 JSON-LD（第一个含 contentUrl 的对象）。"""
    out = {"ok": False, "category": "", "tags": [], "width": 0, "height": 0,
           "fileSize": "", "creator": "", "publishDate": "", "downloadCount": 0,
           "mediaType": "", "previewUrl": "", "fullTitle": ""}
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


def fetch_one(wtId):
    with _done_guard:
        if str(wtId) in _done:
            return None
    html = http_get(DETAIL_URL.format(wtid=wtId))
    if not html:
        rec = {"wtId": str(wtId), "ok": False, "category": "", "tags": [], "width": 0,
               "height": 0, "fileSize": "", "creator": "", "publishDate": "",
               "downloadCount": 0, "mediaType": "", "previewUrl": "", "fullTitle": ""}
    else:
        rec = parse_detail_html(html)
        rec["wtId"] = str(wtId)
    # 写 checkpoint（线程内串行化，避免并发写坏行）
    with _write_guard:
        with open(CKPT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if rec.get("ok"):
            with _done_guard:
                _done.add(str(wtId))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多采多少个（0=全量）")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    ensure_done_set()
    print(f"checkpoint 已完成: {len(_done)}")

    ids = []
    with open(DATA, encoding="utf-8") as f:
        for row in json.load(f):
            wid = str(row.get("id") or "")
            if wid and wid not in _done:
                ids.append(wid)
    print(f"待采: {len(ids)}")

    if args.limit:
        ids = ids[:args.limit]
        print(f"本次试跑: {len(ids)}")

    done = ok = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(fetch_one, i) for i in ids]
        for fu in as_completed(futs):
            rec = fu.result()
            if rec is None:
                continue
            done += 1
            if rec.get("ok"):
                ok += 1
            if done % 50 == 0:
                elapsed = time.time() - t0
                print(f"  {done}/{len(ids)}  ok={ok}  速率={done/elapsed:.1f}/s  预计剩余={(len(ids)-done)/max(done/elapsed,0.1):.0f}s")

    print(f"完成: {done} 成功 {ok} / 失败 {done-ok}，用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
