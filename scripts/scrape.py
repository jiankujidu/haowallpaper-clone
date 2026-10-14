#!/usr/bin/env python3
"""
哲风壁纸 clone —— 全站采集脚本（边采边存 checkpoint + 断点续传）
===================================================================
设计要点：
  * 列表页逐页抓取，**每采一页立即 append 到 downloads/checkpoint/<source>.jsonl**。
    任何时刻崩溃 / 中断，重跑都会从 checkpoint 里已完成的页接着来，
    既不会丢已采数据，也不重复下载已存在的海报。
  * 文件级去重：downloads/posters/<source>/<safe_title>_<urlbasename>.png，
    已存在的直接复用（不重下）。
  * 海报名里的 Windows 路径非法字符（/ \\ : * ? " < > |）会被替换成下划线，
    避免 write_bytes 因“子目录不存在”而 FileNotFoundError。

用法：
  python scripts/scrape.py --listers homeView --max-pages 0 --resume --workers 8
  python scripts/scrape.py --listers homeView,mobileView --max-pages 3     # 试跑 3 页
  python scripts/scrape.py --listers homeView --with-video                 # 连视频一起下

说明：
  - 目标站（Nuxt SPA）列表页把每页 12 张卡片序列化在
    <script type="application/ld+json"> 的 CollectionPage → ItemList 里
    （url / name / image 海报）。据此枚举全部页，?page=N 翻页。
  - homeView（电脑壁纸）实测共 4760 页 ≈ 5.7 万张海报。
  - 默认只下**海报图**（轻量、可预览）；--with-video 才下 mp4。
  - 可选 --fill-details 抓详情页明文正文补全 分类/分辨率/色系/大小/下载量/收藏量/标签。
"""
import argparse, json, os, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "downloads"
POSTERS = OUT / "posters"
VIDEOS = OUT / "videos"
DATA = OUT / "data"
CHECKPOINT = OUT / "checkpoint"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://haowallpaper.com"

LISTERS = {
    "homeView": "/homeViewLook/",     # 电脑壁纸
    "mobileView": "/mobileViewLook/", # 手机壁纸
}


def http_get(url, timeout=30, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if i == retries - 1:
                print(f"    [warn] 获取失败 {url} : {e}")
                return None
            time.sleep(1 + i)
    return None


def parse_listing(html):
    """从列表页 JSON-LD 的 CollectionPage → ItemList 解析该页卡片。"""
    items = []
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
        block = block.strip()
        try:
            obj = json.loads(block)
        except Exception:
            continue
        main = obj.get("mainEntity") or {}
        for li in main.get("itemListElement", []):
            url = li.get("url", "")
            m = re.search(r'/[a-zA-Z]+Look/(\d+)$', url)
            items.append({
                "id": m.group(1) if m else li.get("image", ""),
                "url": url,
                "title": (li.get("name") or "").split("「哲风壁纸」")[0].strip() or "未命名壁纸",
                "poster": li.get("image", ""),
                "video": "", "category": "", "resolution": "", "colorTone": "",
                "size": "", "downloads": 0, "favorites": 0, "publishDate": "", "tags": [],
            })
    return items


def fetch_detail_fields(url, timeout=25):
    """抓详情页，补全 video / category / 各项元数据。失败返回 {} 不影响流程。"""
    html = http_get(url, timeout=timeout)
    if not html:
        return {}
    text = html.decode("utf-8", "ignore")
    plain = re.sub(r'<[^>]+>', ' ', text)
    plain = re.sub(r'\s+', ' ', plain)

    def grab(label, pattern):
        m = re.search(label + r'[：:]\s*' + pattern, plain)
        return m.group(1) if m else ""

    cat  = grab("分类", r"([^，、]+)")
    res  = grab("分辨率", r"「?([\dx]+)」?")
    col  = grab("色系", r"([^，、]+)")
    size = grab("大小", r"([\d.]+\s*MB)")
    dl   = grab("下载量", r"(\d+)")
    fav  = grab("收藏量", r"(\d+)")
    date = grab("发布时间", r"(\d{4}-\d{2}-\d{2})")

    tags = []
    ti = plain.find("相关标签"); te = plain.find("相关收藏")
    if ti != -1 and te != -1 and te > ti:
        seg = plain[ti + 4: te]
        tags = [t for t in re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{1,12}', seg) if 1 <= len(t) <= 12][:12]

    vm = re.search(r'<video[^>]*?src="([^"]+)"', text)
    pm = re.search(r'<video[^>]*?poster="([^"]+)"', text)

    return {
        "video": vm.group(1) if vm else "",
        "category": cat, "resolution": res, "colorTone": col, "size": size,
        "downloads": int(dl or 0), "favorites": int(fav or 0),
        "publishDate": date, "tags": tags,
        "poster": pm.group(1) if pm else "",
    }


def fetch_listing_page(lister, page, max_pages):
    """抓一个列表页，返回 (该页 items, 是否还有下一页)。"""
    url = f"{BASE}/{lister}?page={page}"
    html = http_get(url)
    if not html:
        return [], False
    items = parse_listing(html.decode("utf-8", "ignore"))
    has_more = page < max_pages and bool(items)
    return items, has_more


def slugify(s):
    s = re.sub(r'[\\/:*?"<>|\u4e00-\u9fa5]+', '', s or "")
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    return s or "unknown"


def _safe_prefix(title):
    """把标题转成安全文件名片段：去掉 OS 非法字符（/\\:*?\"<>|），保留中文。"""
    s = re.sub(r'[\\/:*?"<>|]', '_', title or "")
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:30]


def poster_dest(it):
    """海报落盘路径：downloads/posters/<source>/<safe_title>_<urlbasename>.png"""
    dest_dir = POSTERS / slugify(it.get("source", "homeView"))
    fname = _safe_prefix(it.get("title", "")) + "_" + os.path.basename(it.get("poster", ""))
    return dest_dir, dest_dir / fname


def download_asset(url, dest_dir, prefix):
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_prefix(prefix) + "_" + url.rsplit("/", 1)[-1]
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    data = http_get(url, timeout=60)
    if data:
        dest.write_bytes(data)
        return str(dest)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=5, help="每个列表页最多抓取多少页（0=抓到没有为止）")
    ap.add_argument("--with-video", action="store_true", help="同时下载 mp4 视频（体积大）")
    ap.add_argument("--listers", default="homeView,mobileView", help="逗号分隔的列表页")
    ap.add_argument("--workers", type=int, default=4, help="并发下载线程数")
    ap.add_argument("--fill-details", action="store_true",
                    help="额外抓详情页补全 分类/分辨率/色系/大小/下载量/收藏量/标签（较慢）")
    ap.add_argument("--resume", action="store_true",
                    help="断点续传：从 checkpoint 接着采 + 跳过已下载的海报")
    args = ap.parse_args()

    listers = [l.strip() for l in args.listers.split(",") if l.strip()]
    for d in (OUT, POSTERS, CHECKPOINT, DATA):
        d.mkdir(parents=True, exist_ok=True)

    # ---------- 文件锁：防止多进程同时写同一 checkpoint ----------
    lock_path = CHECKPOINT / f"lock.{listers[0]}"
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        import fcntl
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        # Windows：msvcrt，使用非阻塞加锁
        import msvcrt
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("!!! 已有采集进程在运行，退出以避免数据冲突。")
            sys.exit(1)
    except OSError:
        print("!!! 锁被占用（已有进程在跑），退出。")
        sys.exit(1)

    # ---------- checkpoint：每个 source 一个 jsonl，每行一条 item ----------
    def ck(lister):
        return CHECKPOINT / f"{lister}.jsonl"

    def load_ckpt(lister):
        p = ck(lister)
        out = []
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
        return out

    # 已完成的页码（从 checkpoint 各 item 的 _page 推算最大页）
    done_pages = {}
    for lister in listers:
        existing = load_ckpt(lister)
        done_pages[lister] = max([it.get("_page", 0) for it in existing], default=0)
        if existing:
            print(f">>> checkpoint: {lister} 已有 {len(existing)} 条，从 p{done_pages[lister]} 继续")

    # ---------- 逐页抓取 + 即时写 checkpoint（可中断恢复）----------
    for lister in listers:
        start = done_pages[lister] + 1
        print(f"\n===== 列表页 {lister} 从 p{start} 开始 =====")
        page = start
        while True:
            if args.max_pages and page > args.max_pages:
                break
            items, has_more = fetch_listing_page(lister, page, args.max_pages or 10**9)
            if items:
                with ck(lister).open("a", encoding="utf-8") as f:
                    for it in items:
                        it["source"] = lister
                        it["_page"] = page
                        f.write(json.dumps(it, ensure_ascii=False) + "\n")
                print(f"  p{page}: 本页 {len(items)} 条 -> checkpoint", flush=True)
            else:
                print(f"  p{page}: 0 条，已到末尾", flush=True)
            if not items or not has_more:
                break
            page += 1
            time.sleep(0.2 + random.random() * 0.35)  # 礼貌限速

    # ---------- 汇总 checkpoint（去重）----------
    print("\n===== 汇总 checkpoint =====")
    all_items, seen = [], set()
    for lister in listers:
        for line in ck(lister).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            it = json.loads(line)
            key = it.get("video") or it.get("poster")
            if key and key not in seen:
                seen.add(key)
                all_items.append(it)
    print(f"共 {len(all_items)} 条（去重后）")

    # ---------- 可选：抓详情补全 ----------
    if args.fill_details:
        need = [it for it in all_items if not it.get("resolution")]
        print(f"\n>>> 抓取 {len(need)} 个详情页补全元数据 ...")
        for i, it in enumerate(need, 1):
            f = fetch_detail_fields(it["url"])
            if f.get("poster"):
                it["poster"] = f["poster"]
            it["video"] = f.get("video") or it.get("video", "")
            for k in ["category", "resolution", "colorTone", "size",
                      "downloads", "favorites", "publishDate", "tags"]:
                if f.get(k):
                    it[k] = f[k]
            if i % 30 == 0:
                print(f"    详情 {i}/{len(need)}")
            time.sleep(0.12)

    # ---------- 下载海报（文件级去重，已存在的复用）----------
    print("\n>>> 下载海报 ...")
    def _dl(it):
        dest_dir, dest = poster_dest(it)
        if dest.exists() and dest.stat().st_size > 0:
            it["localPoster"] = os.path.relpath(dest, ROOT)
            return str(dest)
        d = download_asset(it.get("poster"), dest_dir, it.get("title", ""))
        it["localPoster"] = os.path.relpath(d, ROOT) if d else ""
        return d
    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(_dl, all_items):
            if r:
                ok += 1
    print(f"海报 {ok}/{len(all_items)}")

    # ---------- 可选：下载视频 ----------
    if args.with_video:
        print("\n>>> 下载视频 ...")
        def _dv(it):
            d = download_asset(it.get("video"), VIDEOS / slugify(it.get("source", "homeView")), _safe_prefix(it.get("title", "")))
            it["localVideo"] = os.path.relpath(d, ROOT) if d else ""
            return d
        with ThreadPoolExecutor(max_workers=max(2, args.workers // 2)) as ex:
            list(ex.map(_dv, all_items))
        print(f"视频 {sum(1 for i in all_items if i.get('localVideo'))}/{len(all_items)}")

    # ---------- 输出最终 JSON ----------
    for it in all_items:
        it.pop("_page", None)
        it.pop("_poster_path", None)
    out = DATA / "wallpapers.json"
    out.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n数据写入 {out}  ({len(all_items)} 条)")
    print("提示：python scripts/sync_site.py 同步进 website/，再刷新 http://127.0.0.1:8091/")


if __name__ == "__main__":
    main()
