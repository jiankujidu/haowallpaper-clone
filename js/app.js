/* 哲风壁纸 clone — 前端逻辑
 * 数据加载三级回退：
 *   1) /api/wallpapers.json        明文版（本地/同源场景）
 *   2) /api/wallpapers.json.gz     GitHub Pages 场景，DecompressionStream 解压
 *   3) /downloads/data/wallpapers.json  33MB 明文兜底（兼容不支持 DecompressionStream 的老浏览器）
 * 海报路径多级回退：downloads/posters/（Pages / 根目录）→ posters/（website 目录）→ 原站 URL
 * 列表 / 详情 / 搜索 / 筛选 / 分页
 */

const BASE = '';               // 同源；若跨域改成 'http://host:port'
const PER_PAGE = 12;           // 与目标站一致

const state = { all: [], filteredList: [], page: 1, detail: null };

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
  const loaders = [
    () => fetchJson(BASE + '/api/wallpapers.json'),
    () => fetchGzipJson(BASE + '/api/wallpapers.json.gz'),
    () => fetchJson(BASE + '/downloads/data/wallpapers.json'),
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
  applyFilters();
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

function applyFilters() {
  const cat = document.querySelector('.cat-tab.active')?.dataset.cat || '全部';
  const kw = (document.getElementById('searchInput').value || '').trim().toLowerCase();

  let list = state.all;
  if (cat && cat !== '全部') list = list.filter(w => w.category === cat);
  if (kw) list = list.filter(w =>
    (w.title + (w.tags || []).join(' ')).toLowerCase().includes(kw));

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
    return `
    <div class="card" data-id="${w.id}">
      <div class="card-media">
        <img loading="lazy" src="${urls[0] || w.poster}" alt="${escapeHtml(w.title)}">
        <span class="card-badge">${escapeHtml(w.category || '壁纸')}</span>
      </div>
      <div class="card-title" title="${escapeHtml(w.title)}">${escapeHtml(w.title)}</div>
      <div class="card-sub">
        <span class="cat">${escapeHtml(w.category || '')}</span>
        <span class="dl">⬇ ${fmt(w.downloads)} · ★ ${fmt(w.favorites)}</span>
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

  // 媒体区：海报图为主（视频多为原站防盗链资源，能播才叠加）
  const urls = posterCandidates(w);
  const img = document.getElementById('detailImg');
  img.src = urls[0] || w.poster || '';
  bindImgFallback(img, urls);

  const v = document.getElementById('detailVideo');
  v.classList.add('hidden');
  v.onerror = () => v.classList.add('hidden');
  v.onloadeddata = () => v.classList.remove('hidden');
  if (w.video) {
    v.src = w.video;
    v.load();
    v.play().catch(() => {});
  } else {
    v.removeAttribute('src');
  }

  document.getElementById('dTitle').textContent = w.title;
  document.getElementById('dMeta').innerHTML = `
    <div>分类：<b>${escapeHtml(w.category || '—')}</b></div>
    <div>分辨率：<b>${escapeHtml(w.resolution || '—')}</b></div>
    <div>色系：<b>${escapeHtml(w.colorTone || '—')}</b></div>
    <div>大小：<b>${escapeHtml(w.size || '—')}</b></div>
    <div>下载量：<b>${fmt(w.downloads)}</b></div>
    <div>收藏量：<b>${fmt(w.favorites)}</b></div>
    <div>发布时间：<b>${escapeHtml(w.publishDate || '—')}</b></div>`;
  document.getElementById('dTags').innerHTML =
    (w.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('') ||
    '<span class="muted" style="color:var(--muted)">暂无标签</span>';
  document.getElementById('dCreator').innerHTML = `
    <span class="avatar"></span>
    <div>
      <div class="c-name">哲风壁纸</div>
      <div class="c-stat">粉丝 ${fmt(w.creator?.fans)} ｜ 分享 ${fmt(w.creator?.shares)}</div>
    </div>`;
  // 下载：直接存本地海报图（原站视频/图片有防盗链，下载会失败）
  document.getElementById('dlBtn').onclick = () => {
    const a = document.createElement('a');
    a.href = urls[0] || w.poster;
    a.download = (w.title || 'wallpaper') + '.png';
    document.body.appendChild(a); a.click(); a.remove();
  };

  // 相关推荐：同分类取 3 条
  const rel = state.all.filter(x => x.category === w.category && x.id !== w.id).slice(0, 3);
  document.getElementById('dRelated').innerHTML = rel.map(r => {
    const ru = posterCandidates(r);
    return `
    <div class="rel-card" data-id="${r.id}">
      <img loading="lazy" src="${ru[0] || r.poster}" alt="${escapeHtml(r.title)}">
      <p>${escapeHtml(r.title)}</p>
    </div>`;
  }).join('') || '';
  document.querySelectorAll('#dRelated .rel-card').forEach(c => {
    const r = rel.find(x => String(x.id) === c.dataset.id);
    c.addEventListener('click', () => openDetail(c.dataset.id));
    const rimg = c.querySelector('img');
    if (rimg && r) bindImgFallback(rimg, posterCandidates(r));
  });

  window.scrollTo({ top: 0, behavior: 'smooth' });
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
  document.querySelectorAll('.cat-tab').forEach(t =>
    t.addEventListener('click', () => {
      document.querySelectorAll('.cat-tab').forEach(x => x.classList.remove('active'));
      t.classList.add('active');
      applyFilters();
    }));

  let timer;
  document.getElementById('searchInput').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!document.getElementById('detail').classList.contains('hidden')) closeDetail();
      applyFilters();
    }, 250);
  });

  document.getElementById('backBtn').addEventListener('click', closeDetail);

  // 顶栏导航切换（此处统一切到"全部"分类）
  document.querySelectorAll('.nav-link').forEach(n => n.addEventListener('click', e => {
    e.preventDefault();
    document.querySelectorAll('.nav-link').forEach(x => x.classList.remove('active'));
    n.classList.add('active');
    document.querySelectorAll('.cat-tab').forEach(x => x.classList.remove('active'));
    document.querySelector('.cat-tab[data-cat="全部"]').classList.add('active');
    if (!document.getElementById('grid').classList.contains('hidden')) closeDetail();
    applyFilters();
  }));

  await loadAll();
});
