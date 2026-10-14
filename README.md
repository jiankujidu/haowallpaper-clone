# 哲风壁纸 Clone（haowallpaper.com）

复刻目标站 https://haowallpaper.com 的 **高清 4K 电脑 / 手机动态壁纸** 网站，
并用脚本采集其全部壁纸海报图与元数据。

## 目录结构

```
website/            clone 网站（静态，可直接用任意 HTTP 服务托管）
  index.html        单页：列表 + 详情 + 搜索 + 筛选 + 分页
  css/style.css     深色主题样式（仿目标站 darkBody）
  js/app.js         前端逻辑（读取 /api/wallpapers.json）
  api/wallpapers.json  采集到的壁纸数据（驱动网站）
scripts/
  scrape.py         采集脚本（爬列表页 + 详情页 + 下载海报）
downloads/
  data/wallpapers.json   采集出的结构化数据
  posters/             下载的海报图（png，已 gitignore）
  videos/              下载的 mp4（可选，已 gitignore）
```

## 快速运行

### 1. 本地预览 clone 网站
```bash
cd website
python -m http.server 8091      # 浏览器打开 http://127.0.0.1:8091/
```

### 2. 采集数据（默认轻量：只下海报图）
```bash
# 快速试跑（前 3 页，约 36 张）
python scripts/scrape.py --max-pages 3 --listers homeView

# 全量 + 补全详情字段（分类/分辨率/色系/大小/下载量/收藏量/标签）
python scripts/scrape.py --max-pages 60 --listers homeView,mobileView --fill-details

# 连视频（mp4）一起下（体积大，慎用）
python scripts/scrape.py --max-pages 30 --listers homeView --with-video
```

### 3. 把数据同步进网站
采集后，把 `downloads/data/wallpapers.json` 复制到 `website/api/wallpapers.json`：
```bash
cp downloads/data/wallpapers.json website/api/wallpapers.json
```
刷新浏览器即可看到最新数据。

## 工作原理

目标站是 **Nuxt (Vue) SPA**，列表页把每页 12 张卡片序列化在
`<script type="application/ld+json">` 的 `CollectionPage → ItemList` 里，
含 `url / name / image(海报)`。脚本据此枚举全部页：

- 列表页 `homeView`（电脑壁纸）/ `mobileView`（手机壁纸），每页 12–13 张；
- 翻页用 `?page=N`，终止于目标页数为空或达到 `--max-pages`；
- 可选 `--fill-details` 抓详情页明文正文（`分类：xx、分辨率：「WxH」、色系、大小、
  下载量、收藏量、发布时间、相关标签`）补全字段；
- 默认只下载**海报图**（轻量、可预览），`--with-video` 才下载 mp4。

> 注意：目标站详情正文里还有一份**加密的 Nuxt payload**（base64+ 混淆），
> 正文可读字段都在明文区，直接正则即可提取，无需解密。

## 采集的全部图片清单（示例，24 张）

`downloads/posters/` 下按来源分目录：`homeView/`、`mobileView/`。
每张海报对应一条 `wallpapers.json` 记录（含本地路径 `localPoster`）。

## 关于"一模一样"的说明

这是**功能与视觉复刻**（布局、深色主题、列表/详情/搜索/分页/相关推荐），
**未照搬目标站的 Nuxt 构建产物、加密逻辑与图片素材版权**，仅供学习研究，请勿商用。
