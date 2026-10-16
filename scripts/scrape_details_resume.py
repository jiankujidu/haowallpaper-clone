#!/usr/bin/env python3
"""
断点续采详情页：
  * 只采 wallpapers.json 里数字 id 还没在 details.jsonl ok 里的
  * 遇到 502/503 指数退避重试，全批 502 时 sleep 30s
  * 每 100 个打一次进度
  * 支持断点：重跑自动从 checkpoint 接着来

用法：
  python scripts/scrape_details_resume.py --workers 4
"""
import argparse, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "downloads" / "data" / "wallpapers.json"
CKPT = ROOT / "downloads" / "checkpoint" / "details.jsonl"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DETAIL_URL = "https://haowallpaper.com/homeViewLook/{wtid}"

import threading
_write_guard = threading.Lock()
_done = set()
_fail_streak = 0
_streak_lock = threading.Lock()


def load_done():
    global _done
    if not CKPT.exists():
        return
    for line in open(CKPT, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("ok") and rec.get("wtId"):
            _done.add(str(rec["wtId"]))
    print(f"checkpoint 已采: {len(_done)}")


def load_todo():
    data = json.load(open(DATA, encoding="utf-8"))
    todo = []
    for r in data:
        wid = str(r.get("id") or "")
        # 只采数字 id（排除 hash/URL 脏数据）
        if wid.isdigit() and wid not in _done:
            todo.append(wid)
    print(f"待采: {len(todo)}")
    return todo


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


def http_get(url, timeout=20, retries=4):
    global _fail_streak
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://haowallpaper.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            if i == retries - 1:
                return None
            err_code = getattr(e, "code", 0)
            if err_code in (502, 503):
                # 指数退避，上限 15s
                wait = min(2 * (2 ** i), 15)
                time.sleep(wait)
            else:
                time.sleep(1.5 + i)
    return None


def fetch_one(wtId):
    global _fail_streak
    html = http_get(DETAIL_URL.format(wtid=wtId))
    if not html:
        rec = {"wtId": str(wtId), "ok": False, "category": "", "tags": [], "width": 0,
               "height": 0, "fileSize": "", "creator": "", "publishDate": "",
               "downloadCount": 0, "mediaType": "", "previewUrl": "", "fullTitle": "",
               "colorTone": ""}
    else:
        rec = parse_detail_html(html)
        rec["wtId"] = str(wtId)
    with _write_guard:
        with open(CKPT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if rec.get("ok"):
            _done.add(str(wtId))
            with _streak_lock:
                _fail_streak = 0
    return rec


def http_get(url, timeout=20, retries=4):
    global _fail_streak
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://haowallpaper.com/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            if i == retries - 1:
                return None
            err_code = getattr(e, "code", 0)
            if err_code in (502, 503):
                wait = min(2 * (2 ** i), 15)
                time.sleep(wait)
            else:
                time.sleep(1.5 + i)
    return None


def probe_site():
    """快速探测站点是否恢复（用已知 ok 的 id 测试，超时 5s）。"""
    global _fail_streak
    if not _done:
        return False
    sample = next(iter(_done))
    try:
        req = urllib.request.Request(
            DETAIL_URL.format(wtid=sample),
            headers={"User-Agent": UA, "Referer": "https://haowallpaper.com/"})
        html = urllib.request.urlopen(req, timeout=8).read()
        if len(html) > 1000:
            with _streak_lock:
                _fail_streak = 0
            print(f"[probe] 站点恢复 ✓ ({len(html)} B)")
            return True
    except Exception:
        pass
    return False


def main_loop(args, batch_size=5000):
    """外层循环：每批采 batch_size 个，全批 502 时进入探测等待。"""
    while True:
        load_done()
        todo = load_todo()
        if not todo:
            print("全部采完了，退出")
            return
        print(f"\n=== 新一批: {len(todo)} 个待采 ===")
        batch = todo[:batch_size]
        done = ok = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(fetch_one, i) for i in batch]
            for fu in as_completed(futs):
                rec = fu.result()
                done += 1
                if rec.get("ok"):
                    ok += 1
                if done % 100 == 0:
                    elapsed = time.time() - t0
                    print(f"  {done}/{len(batch)}  ok={ok}  速率={done/elapsed:.1f}/s  "
                          f"累计ok={len(_done)}")
        print(f"本批完成: {done} 成功 {ok} / 失败 {done-ok}，用时 {time.time()-t0:.0f}s")
        # 全批失败 → 站点挂，进入探测等待
        if ok == 0:
            print("全批失败（502 持续），进入探测模式，每 60s 探测一次...")
            while True:
                time.sleep(60)
                if probe_site():
                    print("站点已恢复，继续下一批")
                    break
        # 有进展则继续下一批
        load_done()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="本次最多采多少个（0=全量）")
    ap.add_argument("--batch", type=int, default=5000, help="每批最多采多少个")
    ap.add_argument("--oneloop", action="store_true", help="只跑一批（不循环探测）")
    args = ap.parse_args()

    CKPT.parent.mkdir(parents=True, exist_ok=True)
    if not CKPT.exists():
        CKPT.touch()
    load_done()

    if args.limit:
        # 试跑模式：只采指定数量
        todo = load_todo()
        if args.limit:
            todo = todo[:args.limit]
            print(f"本次试跑: {len(todo)}")
        if not todo:
            print("全部采完了，退出")
            return
        done = ok = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(fetch_one, i) for i in todo]
            for fu in as_completed(futs):
                rec = fu.result()
                done += 1
                if rec.get("ok"):
                    ok += 1
                if done % 100 == 0:
                    elapsed = time.time() - t0
                    print(f"  {done}/{len(todo)}  ok={ok}  速率={done/elapsed:.1f}/s  "
                          f"累计ok={len(_done)}")
        print(f"\n本批完成: {done} 成功 {ok} / 失败 {done-ok}，用时 {time.time()-t0:.0f}s")
        print(f"累计 details: {len(_done)}")
        return

    # 全量循环模式
    main_loop(args, batch_size=args.batch)


if __name__ == "__main__":
    main()
