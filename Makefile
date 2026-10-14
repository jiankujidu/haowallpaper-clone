# 哲风壁纸 clone —— 一键命令
# 用法（本机 python 在 PATH）：
#   make scrape     全量采集 homeView（可中断，重跑加 RESUME=1）
#   make sync       同步数据+海报进 website（演示用 60 条：make sync N=60）
#   make site       本地起服务预览
#   make commit     规范化提交（含 LFS 媒体）
#   make full       一条龙：采集 -> 同步 -> 提交
#   make status     查看采集进度

PY  ?= python
RESUME ?= 1
N ?= 60

.PHONY: scrape sync site commit full status

scrape:
	$(PY) scripts/scrape.py --listers homeView --max-pages 0 --resume --workers 8

sync:
	$(PY) scripts/sync_site.py --sample $(N)

site:
	cd website && $(PY) -m http.server 8091

commit:
	git add .gitattributes .gitignore README.md Makefile scripts/ website/ \
		downloads/data/wallpapers.json downloads/posters/
	git commit -m "data: 同步最新采集数据与海报（LFS）"

full: scrape sync commit

status:
	@echo "已下载海报: $(shell find downloads/posters -name '*.png' 2>/dev/null | wc -l)"
	@tail -c 200 downloads/scrape_full.log 2>/dev/null | grep -oiE 'homeView p[0-9]+' | tail -1 || true
