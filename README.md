# 哲风壁纸 Clone（haowallpaper.com）

复刻目标站 https://haowallpaper.com 的 **高清 4K 电脑 / 手机动态壁纸** 网站，
并用脚本采集其全部壁纸海报图与元数据，用 **git（+ LFS）** 管理整个项目。

## 目录结构

```
website/            clone 网站（静态，可直接用任意 HTTP 服务托管）
  index.html        单页：列表 + 详情 + 搜索 + 筛选 + 分页
  css/style.css     深色主题样式（仿目标站 darkBody）
  js/app.js         前端逻辑（读 /api/wallpapers.json，本地海报缺失时回退远端）
  api/wallpapers.json  采集到的壁纸数据（驱动网站）
  posters/          同步进来的本地海报（加速显示，可选）
scripts/
  scrape.py         采集脚本（爬列表页 JSON-LD + 抓详情补全 + 下海报，支持断点续传）
  sync_site.py      把 downloads/ 的数据+海报 同步进 website/
downloads/
  data/wallpapers.json   采集出的结构化数据（全量）
  posters/             下载的海报图（png）
  videos/              下载的 mp4（可选）
.gitattributes      git-lfs 跟踪大体积媒体
```

## 一键全流程（推荐顺序）

```bash
# 1) 全量采集（homeView 约 4760 页 ≈ 5.7 万张海报；可中断，重跑加 --resume 续传）
python scripts/scrape.py --listers homeView --max-pages 0 --resume --workers 8

# 2) 同步进网站（全量 5.7 万条喂前端会卡，用 --sample 60 做演示版；要全量就去掉 --sample）
python scripts/sync_site.py --sample 60

# 3) 本地预览
cd website && python -m http.server 8091
# 浏览器打开 http://127.0.0.1:8091/
```

## 用 git 管理

本项目用 git 管理代码 + 数据。全量海报（数万张 PNG，数 GB）用 **git-lfs** 跟踪，
避免撑爆普通 git 历史：

```bash
# 一次性安装 LFS（本机 git-lfs 未装时）
git lfs install

# 把采集成果 + 同步数据一起提交
git add .gitattributes .gitignore README.md scripts/ website/ \
        downloads/data/wallpapers.json downloads/posters/
git commit -m "feat: 哲风壁纸 clone + 全量采集数据 + LFS 管理海报"
```

说明：
- 代码、脚本、`wallpapers.json`（数据）用普通 git 管理。
- `downloads/posters/**/*.png`、`downloads/videos/**/*.mp4` 走 LFS（见 `.gitattributes`）。
- 推送到远程前，需先在 目标 git 服务（如 self-hosted Gitea/GitLab/GitHub 大文件后端）
  启用 LFS，否则 5.7 万张图无法直接 push 到普通仓库。

## 工作原理

目标站是 **Nuxt (Vue) SPA**，列表页把每页 12 张卡片序列化在
`<script type="application/ld+json">` 的 `CollectionPage → ItemList` 里，
含 `url / name / image(海报)`。脚本据此枚举全部页：

- 列表页 `homeView`（电脑壁纸，实测 4760 页）/ `mobileView`（手机壁纸），每页 12–13 张；
- 翻页用 `?page=N`，`--max-pages 0` 表示一直翻到目标站没有为止（自动在末尾页停止）；
- 可选 `--fill-details` 抓详情页明文正文补全 分类/分辨率/色系/大小/下载量/收藏量/标签；
- `--resume` 断点续传：跳过 `downloads/posters/` 里已下载的海报，可安全中断重跑；
- 默认只下载**海报图**（轻量、可预览），`--with-video` 才下载 mp4。

> 注意：目标站详情正文里还有一份**加密的 Nuxt payload**（base64+ 混淆），
> 正文可读字段都在明文区，直接正则即可提取，无需解密。

## 关于"一模一样"的说明

这是**功能与视觉复刻**（布局、深色主题、列表/详情/搜索/分页/相关推荐），
**未照搬目标站的 Nuxt 构建产物、加密逻辑与图片素材版权**，仅供学习研究，请勿商用。

