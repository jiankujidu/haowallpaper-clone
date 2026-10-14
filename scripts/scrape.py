#!/usr/bin/env python3
"""
哲风壁纸 clone —— 全站采集脚本
================================
功能：
  1. 爬取 haowallpaper.com 的列表页（homeView / mobileView），遍历全部页，
     收集所有壁纸条目（含详情字段：标题/分类/分辨率/色系/大小/下载量/收藏量/发布时间/标签/视频/海报）。
  2. 下载每一张壁纸的海报图（png）到 downloads/posters/。
  3. 可选：下载对应视频（mp4）到 downloads/videos/（--with-video）。
  4. 输出结构化数据 downloads/data/wallpapers.json，供 clone 网站 /api/wallpapers.json 使用。

说明：
  - 目标站为 Nuxt SPA，详情正文是加密 Nuxt payload，直接抓取列表页里的
    <video> 卡片 + 详情链接即可得到 海报/视频/标题/分类 等关键信息。
  - 默认只下载「海报图」（轻量、可预览）；加 --with-video 才会下载体积较大的 mp4。

用法：
  python scripts/scrape.py --max-pages 3            # 快速试跑 3 页
  python scripts/scrape.py --max-pages 60            # 全量（电脑壁纸）
  python scripts/scrape.py --max-pages 60 --with-video   # 连视频一起
"""
import argparse, json, os, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "downloads"
POSTERS = OUT / "posters"
VIDEOS = OUT / "videos"
DATA = OUT / "data"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://haowallpaper.com"

# 列表页 -> 详情前缀
LISTERS = {
    "homeView": "/homeViewLook/",     # 电脑壁纸
    "mobileView": "/mobileViewLook/",  # 手机壁纸
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
    """从列表页解析出该页的壁纸卡片。
    目标站（Nuxt SPA）把每一页的 12 张卡片序列化在 JSON-LD 里：
        <script type="application/ld+json">
          {"@type":"CollectionPage","mainEntity":{"@type":"ItemList",
            "numberOfItems":12,
            "itemListElement":[
              {"position":1,"url":".../homeViewLook/ID","name":"标题","image":"海报"}, ...
            ]}}
        </script>
    这是列表页里最完整、最稳定的数据来源（静态 <video> 只有前几张）。
    详情字段（分辨率/色系/大小/下载量/收藏量/发布时间/标签）在详情页
    的明文（非加密）正文中，可用 fetch_detail_fields 补全。"""
    items = []
    # 逐块解析所有 JSON-LD，找到 ItemList
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
                "video": "",          # 详情页才有的 mp4，由 fetch_detail_fields 填充
                "category": "",       # 详情页才有的分类
                "resolution": "",
                "colorTone": "",
                "size": "",
                "downloads": 0,
                "favorites": 0,
                "publishDate": "",
                "tags": [],
            })
    return items


def fetch_detail_fields(url, timeout=25):
    """抓详情页，补全 video / category / 各项元数据。失败返回 {} 不影响流程。
    目标站详情页正文是明文，关键文本形如：
        分类：动漫｜二次元、分辨率：「3840x2160」、色系：灰/白、大小：28.85 MB、发布人：∞、发布时间：2025-09-13
    （注意 分类 与 分辨率 之间用全角竖线 ｜ 连接，需用字符类而非 [^\\s<]）"""
    html = http_get(url, timeout=timeout)
    if not html:
        return {}
    text = html.decode("utf-8", "ignore")
    # 去掉标签，保留纯文本（全角竖线 ｜ 是正文的一部分，保留）
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

    # 相关标签：正文里“相关标签”后面是一段空格分隔的词，随后是“相关收藏”。
    # 提取该区间内的 2~10 字中文词作为标签。
    tags = []
    ti = plain.find("相关标签")
    te = plain.find("相关收藏")
    if ti != -1 and te != -1 and te > ti:
        seg = plain[ti + 4: te]
        tags = [t for t in re.findall(r'[\u4e00-\u9fa5A-Za-z0-9]{1,12}', seg) if 1 <= len(t) <= 12][:12]

    # 主视频 src / poster（取第一个 <video>）
    vm = re.search(r'<video[^>]*?src="([^"]+)"', text)
    pm = re.search(r'<video[^>]*?poster="([^"]+)"', text)

    return {
        "video": vm.group(1) if vm else "",
        "category": cat,
        "resolution": res,
        "colorTone": col,
        "size": size,
        "downloads": int(dl or 0),
        "favorites": int(fav or 0),
        "publishDate": date,
        "tags": tags,
        "poster": pm.group(1) if pm else "",
    }


def fetch_listing_page(lister, page, max_pages):
    """抓取一个列表页，返回该页 items 与是否还有下一页。"""
    url = f"{BASE}/{lister}?page={page}"
    html = http_get(url)
    if not html:
        return [], False
    text = html.decode("utf-8", "ignore")
    items = parse_listing(text)
    # 终止条件：本页没有新条目 或 页数到达上限
    has_more = page < max_pages and bool(items)
    return items, has_more


def slugify(s):
    s = re.sub(r'[\\/:*?"<>|\u4e00-\u9fa5]+', '', s or "")
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    return s or "unknown"


def download_asset(url, dest_dir, prefix):
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = prefix + "_" + url.rsplit("/", 1)[-1]
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
    ap.add_argument("--max-pages", type=int, default=5, help="每个列表页最多抓取多少页（设 0 表示抓到没有为止）")
    ap.add_argument("--with-video", action="store_true", help="同时下载 mp4 视频（体积大）")
    ap.add_argument("--listers", default="homeView,mobileView", help="逗号分隔的列表页")
    ap.add_argument("--workers", type=int, default=4, help="并发下载线程数")
    ap.add_argument("--fill-details", action="store_true",
                    help="额外抓取每个壁纸的详情页，补全 分类/分辨率/色系/大小/下载量/收藏量/标签（较慢）")
    ap.add_argument("--resume", action="store_true",
                    help="断点续传：跳过 downloads/posters/ 中已存在的海报，继续补全")
    args = ap.parse_args()

    listers = [l.strip() for l in args.listers.split(",") if l.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    POSTERS.mkdir(exist_ok=True)

    # 已下载海报（用于断点续传）
    downloaded = set()
    if args.resume:
        for p in POSTERS.rglob("*.png"):
            downloaded.add(p.name)
        print(f">>> 断点续传：已存在 {len(downloaded)} 张海报，跳过之")

    all_items = []
    seen = set()
    for lister in listers:
        print(f"\n===== 列表页 {lister} 开始 =====")
        page = 1
        stop = False
        while not stop:
            # 达到页数上限（--max-pages>0 时）
            if args.max_pages and page > args.max_pages:
                break
            items, has_more = fetch_listing_page(lister, page, args.max_pages or 10**9)
            new = 0
            for it in items:
                it["source"] = lister
                key = it["video"] or it["poster"]
                if key not in seen:
                    seen.add(key)
                    base = os.path.basename(it["poster"])
                    if base in downloaded:
                        # 断点续传：海报已存在，补 localPoster 指向已有文件
                        it["localPoster"] = f"downloads/posters/{slugify(lister)}/{base}"
                        all_items.append(it)
                        continue
                    all_items.append(it)
                    new += 1
            print(f"  {lister} p{page}: 本页 {len(items)} 条, 新增 {new}", end="", flush=True)
            # 终止条件：本页 0 条（目标站没有更多）
            if not items:
                print("  <- 已到末尾")
                stop = True
            elif not has_more:
                stop = True
            page += 1
            time.sleep(0.25 + random.random() * 0.4)  # 礼貌限速

    print(f"\n===== 共收集 {len(all_items)} 条壁纸 =====")

    # 可选：抓取详情页补全元数据
    if args.fill_details:
        print(f"\n>>> 正在抓取 {len(all_items)} 个详情页补全元数据 ...")
        for idx, it in enumerate(all_items, 1):
            fields = fetch_detail_fields(it["url"])
            # 详情页的 video/poster 更权威，覆盖之
            it["video"] = fields.get("video") or it.get("video", "")
            if fields.get("poster"):
                it["poster"] = fields["poster"]
            for k in ["category", "resolution", "colorTone", "size",
                      "downloads", "favorites", "publishDate", "tags"]:
                if fields.get(k):
                    it[k] = fields[k]
            if idx % 20 == 0 or idx == len(all_items):
                print(f"    详情 {idx}/{len(all_items)} 完成")
            time.sleep(0.15)

    # 下载海报（并发，断点续传时跳过已存在的）
    def _dl_poster(it):
        base = os.path.basename(it["poster"])
        if args.resume and base in downloaded:
            it["localPoster"] = f"downloads/posters/{slugify(it['source'])}/{base}"
            return True

    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for r in ex.map(_dl_poster, all_items):
            if r:
                ok += 1
    print(f"海报下载成功 {ok}/{len(all_items)}")

    # 可选：下载视频
    if args.with_video:
        def _dl_video(it):
            dest_dir = VIDEOS / slugify(it["source"])
            d = download_asset(it["video"], dest_dir, it["title"][:30])
            it["localVideo"] = os.path.relpath(d, ROOT) if d else ""
            return d
        with ThreadPoolExecutor(max_workers=max(2, args.workers // 2)) as ex:
            list(ex.map(_dl_video, all_items))
        print(f"视频下载成功 {sum(1 for i in all_items if i.get('localVideo'))}/{len(all_items)}")

    # 输出 JSON（清理内部字段）
    for it in all_items:
        it.pop("_poster_path", None)
    DATA.mkdir(exist_ok=True)
    data_file = DATA / "wallpapers.json"
    data_file.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n数据已写入 {data_file}  ({len(all_items)} 条)")
    print("提示：把 downloads/data/wallpapers.json 复制到 website/api/wallpapers.json 即可驱动 clone 网站")


if __name__ == "__main__":
    main()
