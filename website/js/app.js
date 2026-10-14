/* 哲风壁纸 clone — 前端逻辑
 * 通过 /api/wallpapers 读取本地采集数据（或同源 API）
 * 列表 / 详情 / 搜索 / 筛选 / 分页
 */

const BASE = '';               // 同源；若跨域改成 'http://host:port'
const PER_PAGE = 12;           // 与目标站一致

const state = {
  all: [],          // 当前筛选后的全部数据
  page: 1,
  detail: null,
};

/* ---------- 数据加载 ---------- */
async function loadAll() {
  const res = await fetch(BASE + '/api/wallpapers.json');
  if (!res.ok) throw new Error('数据加载失败: ' + res.status);
  const data = await res.json();
  state.all = data;
  applyFilters();
}

// 本地海报路径（由 scripts/sync_site.py 生成），缺失时回退远端 URL
function localPoster(w) {
  const base = (w.poster || '').split('/').pop();
  if (!base) return '';
  return `posters/${w.source || 'homeView'}/${base}`;
}

function withRemoteFallback(w, imgEl) {
  imgEl.onerror = () => { imgEl.onerror = null; imgEl.src = w.poster; };
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

  grid.innerHTML = pageItems.map(w => `
    <div class="card" data-id="${w.id}">
      <div class="card-media">
        <img loading="lazy" src="${localPoster(w) || w.poster}" alt="${escapeHtml(w.title)}">
        <span class="card-badge">${escapeHtml(w.category || '壁纸')}</span>
      </div>
      <div class="card-title" title="${escapeHtml(w.title)}">${escapeHtml(w.title)}</div>
      <div class="card-sub">
        <span class="cat">${escapeHtml(w.category || '')}</span>
        <span class="dl">⬇ ${fmt(w.downloads)} · ★ ${fmt(w.favorites)}</span>
      </div>
    </div>
  `).join('');

  grid.querySelectorAll('.card').forEach(c => {
    c.addEventListener('click', () => openDetail(c.dataset.id));
    const img = c.querySelector('img');
    if (img) withRemoteFallback(pageItems.find(w => w.id === c.dataset.id), img);
  });
}

function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ---------- 详情 ---------- */
function openDetail(id) {
  const w = state.all.find(x => x.id === id);
  if (!w) return;
  state.detail = w;

  const detail = document.getElementById('detail');
  const grid = document.getElementById('grid');
  const pager = document.getElementById('pager');
  grid.classList.add('hidden');
  pager.classList.add('hidden');
  detail.classList.remove('hidden');

  const v = document.getElementById('detailVideo');
  v.poster = w.poster;
  v.src = w.video;
  v.load();
  v.play().catch(() => {});

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
  document.getElementById('dlBtn').onclick = () => {
    const a = document.createElement('a');
    a.href = w.video; a.download = ''; a.target = '_blank'; a.rel = 'noopener';
    document.body.appendChild(a); a.click(); a.remove();
  };

  // 相关推荐：同分类取 3 条
  const rel = state.all.filter(x => x.category === w.category && x.id !== w.id).slice(0, 3);
  document.getElementById('dRelated').innerHTML = rel.map(r => `
    <div class="rel-card" data-id="${r.id}">
      <img loading="lazy" src="${r.poster}" alt="${escapeHtml(r.title)}">
      <p>${escapeHtml(r.title)}</p>
    </div>`).join('') || '';
  document.querySelectorAll('#dRelated .rel-card').forEach(c =>
    c.addEventListener('click', () => openDetail(c.dataset.id)));

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function closeDetail() {
  document.getElementById('detail').classList.add('hidden');
  document.getElementById('grid').classList.remove('hidden');
  document.getElementById('pager').classList.remove('hidden');
  const v = document.getElementById('detailVideo');
  v.pause(); v.removeAttribute('src');
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
      btns += `<button disabled>…</button>`;
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
  document.getElementById('searchInput').addEventListener('input', e => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (document.getElementById('detail')?.classList.contains('hidden') === false) closeDetail();
      e.target.value = e.target.value; applyFilters();
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
    if (!document.getElementById('grid').classList.contains('hidden') === false) closeDetail();
    applyFilters();
  }));

  await loadAll();
});
