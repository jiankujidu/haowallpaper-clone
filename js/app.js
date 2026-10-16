/* 哲风壁纸 clone — 前端逻辑
 * 数据加载三级回退：
 *   1) /api/wallpapers.json        明文版（本地/同源场景）
 *   2) /api/wallpapers.json.gz     GitHub Pages 场景，DecompressionStream 解压
 *   3) /downloads/data/wallpapers.json  33MB 明文兜底（兼容不支持 DecompressionStream 的老浏览器）
 * 海报路径多级回退：downloads/posters/（Pages / 根目录）→ posters/（website 目录）→ 原站 URL
 * 列表 / 详情 / 搜索 / 筛选 / 分页
 */

const BASE = '';               // 同源；若跨域改成 'http://host:port'（数据路径为相对路径，兼容 Pages 项目子路径）
const PER_PAGE = 12;           // 与目标站一致

const state = {
  all: [],
  filteredList: [],
  page: 1,
  detail: null,
  tone: '',            // 色系筛选
  sort: 'default'      // default | dl | newest
};

/* ---------- 加载提示 ---------- */
function showLoading(text) {
  const t = document.getElementById('loadTip');
  if (!t) return;
  t.className = 'load-tip';
  t.innerHTML = '<span class="spinner"></span><span>' + text + '</span>';
}
function showLoadError(msg) {
  const t = document.getElementById('loadTip');
  if (!t) return;
  t.className = 'load-tip load-error';
  t.innerHTML = '<span>' + msg + '</span><button class="ghost-btn" onclick="location.reload()">重新加载</button>';
}
function hideLoading() {
  document.getElementById('loadTip')?.classList.add('hidden');
}

/* ---------- 数据加载 ---------- */
async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url + ' → HTTP ' + res.status);
  return res.json();
}

async function fetchGzipJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(url + ' → HTTP ' + res.status);
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('当前浏览器不支持 DecompressionStream');
  }
  const buf = await res.arrayBuffer();
  const ds = new DecompressionStream('gzip');
  const stream = new Response(buf).body.pipeThrough(ds);
  return JSON.parse(await new Response(stream).text());
}

async function loadAll() {
  showLoading('壁纸数据加载中…');
  // 注意：相对路径（不带前导 /），适配 GitHub Pages 项目子路径 /haowallpaper-clone/
  const loaders = [
    () => fetchJson(BASE + 'api/wallpapers.json'),
    () => fetchGzipJson(BASE + 'api/wallpapers.json.gz'),
    () => fetchJson(BASE + 'downloads/data/wallpapers.json'),
  ];
  let data = null, lastErr = null;
  for (const load of loaders) {
    try { data = await load(); if (data) break; } catch (e) { lastErr = e; }
  }
  if (!data || !data.length) {
    showLoadError('壁纸数据加载失败（' + (lastErr ? lastErr.message : '无数据') + '），请检查网络后重试');
    return;
  }
  state.all = data;
  hideLoading();
  buildCatTabs();
  buildToneTabs();
  applyFilters();
}

/* ---------- 色系 tab（取数量最多的前 8 个色系） ---------- */
function buildToneTabs() {
  const counts = new Map();
  for (const w of state.all) {
    const t = (w.colorTone || '').trim();
    if (t && t !== 'undefined') counts.set(t, (counts.get(t) || 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const wrap = document.getElementById('toneTabs');
  if (!wrap) return;
  wrap.innerHTML = '<button class="tone-tab active" data-tone="">全部色系</button>' +
    top.map(([t, n]) => `<button class="tone-tab" data-tone="${escapeHtml(t)}">${escapeHtml(t)} <i>${fmt(n)}</i></button>`).join('');
  wrap.querySelectorAll('.tone-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      wrap.querySelectorAll('.tone-tab').forEach(x => x.classList.remove('active'));
      btn.classList.add('active');
      state.tone = btn.dataset.tone || '';
      if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
      applyFilters();
    });
  });
}

/* ---------- 海报路径（多级回退） ---------- */
// 逐段 encodeURIComponent：中文/空格/#/% 等都能安全进 URL
function encPath(p) {
  return p.split('/').map(encodeURIComponent).join('/');
}

// 候选 URL 数组：[downloads/posters/…, posters/…, 原站URL]
function posterCandidates(w) {
  const urls = [];
  let rel = '';
  if (w.localPoster) {
    const norm = String(w.localPoster).replace(/\\/g, '/');
    const idx = norm.indexOf('posters/');
    if (idx !== -1) rel = norm.slice(idx + 'posters/'.length);
  }
  if (!rel) {
    const base = (w.poster || '').split('/').pop();
    if (base) rel = (w.source || 'homeView') + '/' + base;
  }
  if (rel) {
    urls.push(encPath('downloads/posters/' + rel));  // GitHub Pages / 仓库根目录本地
    urls.push(encPath('posters/' + rel));            // website/ 目录本地
  }
  if (w.poster) urls.push(w.poster);                 // 原站（防盗链 403，仅最后兜底）
  return urls;
}

// img 加载失败时按候选列表逐个回退
function bindImgFallback(img, urls) {
  let i = 0;
  img.onerror = () => {
    i += 1;
    if (i < urls.length) img.src = urls[i];
    else img.onerror = null;
  };
}

/* ---------- 分类 tab（数据里动态生成，取数量最多的前 10 个真实分类） ---------- */
function buildCatTabs() {
  const counts = new Map();
  for (const w of state.all) {
    const c = (w.category || '').trim();
    if (c && c !== '未定义') counts.set(c, (counts.get(c) || 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
  const wrap = document.getElementById('catTabs');
  wrap.innerHTML = '<button class="cat-tab active" data-cat="全部">全部</button>' +
    top.map(([c, n]) => `<button class="cat-tab" data-cat="${escapeHtml(c)}">${escapeHtml(c)} <i>${fmt(n)}</i></button>`).join('');
  bindCatTabs();
}

function bindCatTabs() {
  document.querySelectorAll('#catTabs .cat-tab').forEach(t =>
    t.addEventListener('click', () => {
      document.querySelectorAll('#catTabs .cat-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
      applyFilters();
    }));
}

function applyFilters() {
  const cat = document.querySelector('#catTabs .cat-tab.active')?.dataset.cat || '全部';
  const kw = (document.getElementById('searchInput').value || '').trim().toLowerCase();
  const tone = state.tone;
  const sort = state.sort;

  let list = state.all;
  if (cat && cat !== '全部') list = list.filter(w => (w.category || '').trim() === cat);
  if (tone) list = list.filter(w => (w.colorTone || '').trim() === tone);
  if (kw) list = list.filter(w =>
    ((w.fullTitle || w.title || '') + ' ' + (w.tags || []).join(' ') + ' ' +
     (w.category || '') + ' ' + (w.colorTone || '') + ' ' + (w.creator || ''))
    .toLowerCase().includes(kw));

  if (sort === 'dl') {
    list = [...list].sort((a, b) => (b.downloadCount || b.downloads || 0) - (a.downloadCount || a.downloads || 0));
  } else if (sort === 'newest') {
    list = [...list].sort((a, b) => (b.publishDate || '').localeCompare(a.publishDate || ''));
  }

  state.filteredList = list;
  state.page = 1;
  renderGrid();
  renderPager();
}

/* ---------- 工具 ---------- */
function fmt(n) {
  n = +n || 0;
  if (n >= 10000) return (n / 10000).toFixed(1) + '万';
  return n;
}

function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------- 列表渲染 ---------- */
function renderGrid() {
  const grid = document.getElementById('grid');
  const list = state.filteredList || [];
  const start = (state.page - 1) * PER_PAGE;
  const pageItems = list.slice(start, start + PER_PAGE);

  if (!pageItems.length) {
    grid.innerHTML = '<div class="empty">暂无符合条件的壁纸</div>';
    return;
  }

  grid.innerHTML = pageItems.map(w => {
    const urls = posterCandidates(w);
    const badge = w.mediaType === 'video' ? '<span class="card-vid">动</span>' : '';
    const res = w.width ? `<span class="card-res">${w.width}×${w.height}</span>` : '';
    const dl  = (w.downloadCount || w.downloads || 0) ? `<span class="card-dl">⬇ ${fmt(w.downloadCount || w.downloads)}</span>` : '';
    return `
    <div class="card" data-id="${w.id}">
      <div class="card-media">
        <img loading="lazy" src="${urls[0] || w.poster}" alt="${escapeHtml(w.title)}">
        ${badge}
        <span class="card-badge">${escapeHtml((w.category || '').trim().split('｜')[0] || '壁纸')}</span>
        <div class="card-hover-info">${res}${dl}</div>
      </div>
      <div class="card-title" title="${escapeHtml(w.fullTitle || w.title)}">${escapeHtml(w.title)}</div>
      <div class="card-sub">
        <span class="cat">${escapeHtml((w.category || '').trim().split('｜')[0] || '')}</span>
        <span class="tone">${escapeHtml(w.colorTone || '')}</span>
      </div>
    </div>`;
  }).join('');

  grid.querySelectorAll('.card').forEach(c => {
    const w = pageItems.find(x => String(x.id) === c.dataset.id);
    c.addEventListener('click', () => openDetail(c.dataset.id));
    const img = c.querySelector('img');
    if (img && w) bindImgFallback(img, posterCandidates(w));
  });
}

/* ---------- 详情 ---------- */
function openDetail(id) {
  const w = state.all.find(x => String(x.id) === String(id));
  if (!w) return;
  state.detail = w;

  const detail = document.getElementById('detail');
  const grid = document.getElementById('grid');
  const pager = document.getElementById('pager');
  grid.classList.add('hidden');
  pager.classList.add('hidden');
  detail.classList.remove('hidden');

  // 媒体区：高清大图优先（previewUrl 是 1100px 预览图，无防盗链），本地 890px 海报兜底
  const hd = (w.previewUrl || '').replace(/^http:\/\//, 'https://');
  const local = posterCandidates(w);
  const img = document.getElementById('detailImg');
  const imgUrls = hd ? [hd, ...local] : local;
  img.src = imgUrls[0] || w.poster || '';
  bindImgFallback(img, imgUrls);

  // 动态壁纸徽标
  const mb = document.getElementById('mediaBadge');
  if (w.mediaType === 'video') {
    mb.textContent = '动态';
    mb.classList.remove('hidden');
  } else {
    mb.classList.add('hidden');
  }
  // 分辨率徽标
  document.getElementById('hdBadge').textContent =
    w.width ? `${w.width}×${w.height}` : '';

  const v = document.getElementById('detailVideo');
  v.classList.add('hidden');
  v.removeAttribute('src');

  document.getElementById('dTitle').textContent = w.fullTitle || w.title;
  document.getElementById('dMeta').innerHTML = `
    <div>分类：<b>${escapeHtml((w.category || '').trim() || '—')}</b></div>
    <div>分辨率：<b>${w.width ? escapeHtml(w.width + '×' + w.height) : '—'}</b></div>
    <div>色系：<b class="d-tone" ${w.colorTone ? `data-tone="${escapeHtml(w.colorTone)}"` : ''}>${escapeHtml(w.colorTone || '—')}</b></div>
    <div>大小：<b>${escapeHtml(w.fileSize || w.size || '—')}</b></div>
    <div>类型：<b>${w.mediaType === 'video' ? '动态壁纸' : '静态壁纸'}</b></div>
    <div>下载量：<b>${fmt(w.downloadCount || w.downloads)}</b></div>
    <div>发布时间：<b>${escapeHtml(w.publishDate || '—')}</b></div>`;
  // 色系可点击 → 触发色系筛选
  const dToneEl = document.querySelector('#dMeta .d-tone[data-tone]');
  if (dToneEl) {
    dToneEl.style.cursor = 'pointer';
    dToneEl.title = '点击按此色系筛选';
    dToneEl.addEventListener('click', () => {
      const toneVal = dToneEl.dataset.tone;
      state.tone = toneVal;
      document.querySelectorAll('#toneTabs .tone-tab').forEach(x =>
        x.classList.toggle('active', x.dataset.tone === toneVal));
      if (document.getElementById('detail').classList.contains('hidden') === false) closeDetail();
      applyFilters();
    });
  }
  // 标签可点击 → 触发搜索
  document.getElementById('dTags').innerHTML =
    (w.tags || []).map(t => `<span class="tag" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`).join('') ||
    '<span class="muted" style="color:var(--muted)">暂无标签</span>';
  document.querySelectorAll('#dTags .tag[data-tag]').forEach(el =>
    el.addEventListener('click', () => {
      const input = document.getElementById('searchInput');
      input.value = el.dataset.tag;
      input.dispatchEvent(new Event('input'));
    }));
  document.getElementById('dCreator').innerHTML = `
    <span class="avatar"></span>
    <div>
      <div class="c-name">${escapeHtml(w.creator || '哲风壁纸')}</div>
      <div class="c-stat">发布人</div>
    </div>`;
  // 下载：优先 fetch 高清大图存本地（img.haowallpaper.com 有 CORS *），失败回退本地海报
  const dlUrl = imgUrls[0] || w.poster;
  const ext = (w.previewUrl || '').endsWith('.mp4') ? 'mp4' : (w.previewUrl ? 'webp' : 'png');
  const fname = ((w.fullTitle || w.title || 'wallpaper').replace(/[\\/:*?"<>|]/g, '_')).slice(0, 60) + '.' + ext;
  document.getElementById('dlBtn').onclick = async () => {
    const btn = document.getElementById('dlBtn');
    btn.disabled = true; btn.textContent = '下载中…';
    try {
      const res = await fetch(dlUrl);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      btn.textContent = '已下载 ✓';
    } catch (e) {
      // 回退：本地海报（相对路径，无 CORS 问题）
      const a = document.createElement('a');
      a.href = local[0] || w.poster;
      a.download = (w.title || 'wallpaper') + '.png';
      document.body.appendChild(a); a.click(); a.remove();
      btn.textContent = '已下载（本地版）';
    }
    setTimeout(() => { btn.disabled = false; btn.textContent = '下载'; }, 3000);
  };

  // 相关推荐：同分类取 3 条
  const rel = state.all.filter(x => (x.category || '').trim() === w.category && String(x.id) !== String(w.id)).slice(0, 3);
  document.getElementById('dRelated').innerHTML = rel.map(r => {
    const ru = posterCandidates(r);
    const rhd = (r.previewUrl || '').replace(/^http:\/\//, 'https://');
    const rurls = rhd ? [rhd, ...ru] : ru;
    return `
    <div class="rel-card" data-id="${r.id}">
      <img loading="lazy" src="${rurls[0] || r.poster}" alt="${escapeHtml(r.title)}">
      <p>${escapeHtml(r.title)}</p>
    </div>`;
  }).join('') || '<div class="empty">暂无相关推荐</div>';
  document.querySelectorAll('#dRelated .rel-card').forEach(c => {
    const r = rel.find(x => String(x.id) === c.dataset.id);
    c.addEventListener('click', () => openDetail(c.dataset.id));
    const rimg = c.querySelector('img');
    if (rimg && r) {
      const rurls = posterCandidates(r);
      const rhd = (r.previewUrl || '').replace(/^http:\/\//, 'https://');
      bindImgFallback(rimg, rhd ? [rhd, ...rurls] : rurls);
    }
  });

  window.scrollTo({ top: 0, behavior: 'smooth' });
  refreshFavBtn();
}

function closeDetail() {
  document.getElementById('detail').classList.add('hidden');
  document.getElementById('grid').classList.remove('hidden');
  document.getElementById('pager').classList.remove('hidden');
  const v = document.getElementById('detailVideo');
  v.pause(); v.removeAttribute('src'); v.classList.add('hidden');
}

/* ---------- 分页 ---------- */
function renderPager() {
  const pager = document.getElementById('pager');
  const total = state.filteredList?.length || 0;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  if (pages <= 1) { pager.innerHTML = ''; return; }

  let btns = `<button data-p="prev" ${state.page === 1 ? 'disabled' : ''}>‹</button>`;
  for (let p = 1; p <= pages; p++) {
    if (p === 1 || p === pages || Math.abs(p - state.page) <= 2) {
      btns += `<button data-p="${p}" class="${p === state.page ? 'active' : ''}">${p}</button>`;
    } else if (p === state.page - 2 || p === state.page + 2) {
      btns += `<button data-p disabled>…</button>`;
    }
  }
  btns += `<button data-p="next" ${state.page === pages ? 'disabled' : ''}>›</button>`;
  pager.innerHTML = btns;

  pager.querySelectorAll('button[data-p]').forEach(b => b.addEventListener('click', () => {
    const p = b.dataset.p;
    if (p === 'prev') state.page = Math.max(1, state.page - 1);
    else if (p === 'next') state.page = Math.min(pages, state.page + 1);
    else state.page = +p;
    renderGrid(); renderPager();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }));
}

/* ---------- 事件绑定 ---------- */
document.addEventListener('DOMContentLoaded', async () => {
  let timer;
  document.getElementById('searchInput').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
      applyFilters();
    }, 250);
  });

  document.getElementById('backBtn').addEventListener('click', closeDetail);

  // Esc 关闭详情
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !document.getElementById('detail').classList.contains('hidden')) {
      closeDetail();
    }
  });

  // 排序切换
  const sortSel = document.getElementById('sortSelect');
  if (sortSel) {
    sortSel.addEventListener('change', () => {
      state.sort = sortSel.value;
      if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
      applyFilters();
    });
  }

  // 收藏（localStorage，纯本地）
  const favBtn = document.getElementById('favBtn');
  const favs = JSON.parse(localStorage.getItem('hzf_favs') || '[]');
  const isFav = id => favs.includes(String(id));
  window.refreshFavBtn = () => { favBtn.textContent = state.detail && isFav(state.detail.id) ? '已收藏 ★' : '收藏'; };
  window.refreshFavBtn();
  favBtn.addEventListener('click', () => {
    const id = String(state.detail?.id);
    if (!id) return;
    const i = favs.indexOf(id);
    if (i >= 0) favs.splice(i, 1); else favs.push(id);
    localStorage.setItem('hzf_favs', JSON.stringify(favs));
    window.refreshFavBtn();
  });

  // 顶栏「首页」：回列表 + 全部分类 + 清空搜索
  document.getElementById('homeLink')?.addEventListener('click', e => {
    e.preventDefault();
    document.getElementById('searchInput').value = '';
    document.querySelectorAll('#catTabs .cat-tab').forEach(x => x.classList.toggle('active', x.dataset.cat === '全部'));
    if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
    applyFilters();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  // 顶栏导航：没有独立路由，统一回「全部 + 清搜索」，保证点了有反应
  document.querySelectorAll('.nav-link').forEach(n => n.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.nav-link').forEach(x => x.classList.remove('active'));
    n.classList.add('active');
    document.getElementById('searchInput').value = '';
    document.querySelectorAll('#catTabs .cat-tab').forEach(x => x.classList.toggle('active', x.dataset.cat === '全部'));
    if (!document.getElementById('grid').classList.contains('hidden')) closeDetail();
    applyFilters();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }));

  await loadAll();
});
