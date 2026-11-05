/**
 * 前端主逻辑（浏览器端）。
 *
 * 关键路径：
 *   导入：文本 → 本地切块 → 本地批量向量化（transformers.js） → POST 向量给本地服务 → 写入 seekdb → 刷新索引
 *   检索：查询文本 → 本地向量化 → POST 查询向量 + 查询原文 → seekdb hybridSearch（数据库侧融合） → 渲染结果
 */
import { Embedder, chunkDocuments, probeBackend } from '/embedder.js';

const $ = (id) => document.getElementById(id);

const state = {
  health: null,
  models: [],
  model: null,
  dtype: 'q8',
  batchSize: 16,
  chunkChars: 480,
  embedder: new Embedder(),
  backend: null,
  collection: null,
  docCount: 0,
  perf: new Map(),
  lastSql: [],
};

/* ------------------------------------------------------------------ */
/* 性能计时                                                             */
/* ------------------------------------------------------------------ */
function recordStage(stage, ms) {
  if (!state.perf.has(stage)) state.perf.set(stage, []);
  const arr = state.perf.get(stage);
  arr.push(ms);
  if (arr.length > 50) arr.shift();
  renderPerf();
}
function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}
function renderPerf() {
  const tbody = $('perf-table').querySelector('tbody');
  tbody.innerHTML = '';
  for (const [stage, arr] of state.perf) {
    const tr = document.createElement('tr');
    const last = arr[arr.length - 1];
    const med = median(arr);
    tr.innerHTML = `<td>${stage}</td>`
      + `<td class="num">${last.toFixed(1)} ms</td>`
      + `<td class="num">${med === null ? '—' : med.toFixed(1) + ' ms'}</td>`
      + `<td class="num">${arr.length}</td>`;
    tbody.appendChild(tr);
  }
}

/* ------------------------------------------------------------------ */
/* 提示条                                                               */
/* ------------------------------------------------------------------ */
function banner(msg, kind = 'info') {
  const el = $('banner');
  el.textContent = msg;
  el.className = `banner ${kind}`;
  el.classList.remove('hidden');
}
function hideBanner() { $('banner').classList.add('hidden'); }

/* ------------------------------------------------------------------ */
/* 初始化                                                               */
/* ------------------------------------------------------------------ */
async function init() {
  const health = await fetch('/api/health').then((r) => r.json());
  state.health = health;
  state.models = health.models;

  const mSel = $('sel-model');
  mSel.innerHTML = '';
  for (const m of health.models) {
    const o = document.createElement('option');
    o.value = m.id;
    o.textContent = `${m.label} · ${m.dim}d`;
    mSel.appendChild(o);
  }
  onModelChange();

  const probe = await probeBackend();
  state.backend = probe;
  paintBackend(probe);

  if (!health.seekdb.reachable) {
    banner('seekdb 服务不可达：请确认本地 seekdb server 已启动（npm run seekdb）。', 'err');
  }

  // 暴露给自动化验证脚本（浏览器内真实执行，无需人工点击）
  window.stepfun = {
    state,
    embedder: state.embedder,
    loadModel: loadModel,
    importDocuments: importDocuments,
    search: search,
    chunkDocuments,
  };
  window.stepfunReady = true;
}

function onModelChange() {
  const id = $('sel-model').value;
  state.model = state.models.find((m) => m.id === id);
  const dSel = $('sel-dtype');
  dSel.innerHTML = '';
  for (const d of state.model.dtypes) {
    const o = document.createElement('option');
    o.value = d;
    o.textContent = { q8: 'INT8 (q8)', fp16: 'FP16', fp32: 'FP32 基线' }[d] || d;
    dSel.appendChild(o);
  }
  dSel.value = state.model.defaultDtype;
  state.dtype = state.model.defaultDtype;
  $('model-value').textContent = `${state.model.id.split('/')[1]} · ${state.dtype}`;
}

function paintBackend(info) {
  const chip = $('chip-backend');
  const val = $('backend-value');
  const isGpu = info.backend === 'webgpu';
  chip.className = `chip ${isGpu ? 'badge-webgpu' : 'badge-wasm'}`;
  val.textContent = isGpu ? 'WebGPU' : 'WASM';
  if (isGpu) {
    const a = info.webgpu?.adapter || {};
    banner(`推理后端：WebGPU${a.vendor ? `（vendor=${a.vendor}, device=${a.device || a.description || 'n/a'}）` : ''}。`
      + ' 文档与查询向量均在本机浏览器内计算。', 'info');
  } else {
    banner(`推理后端：WASM（已从 WebGPU 降级）— ${info.reason || 'WebGPU 不可用'}。`
      + ' 文档与查询向量仍全部在本机浏览器内计算。', 'warn');
  }
}

/* ------------------------------------------------------------------ */
/* 模型加载                                                             */
/* ------------------------------------------------------------------ */
async function loadModel() {
  const modelId = $('sel-model').value;
  const dtype = $('sel-dtype').value;
  state.dtype = dtype;
  state.model = state.models.find((m) => m.id === modelId);
  $('model-value').textContent = `${state.model.id.split('/')[1]} · ${dtype}`;
  hideBanner();
  const t0 = performance.now();
  const info = await state.embedder.load({
    modelId,
    dtype,
    modelMeta: state.model,
    onProgress: (p) => {
      if (p && p.status === 'progress' && p.file) {
        $('import-status').textContent = `下载 ${p.file} ${(p.progress || 0).toFixed(0)}%`;
      }
    },
  });
  recordStage('模型加载（首次，含下载）', state.embedder.loadMs);
  paintBackend(info);
  $('import-status').textContent = `模型就绪（${(performance.now() - t0).toFixed(0)} ms）`;
  return info;
}

/* ------------------------------------------------------------------ */
/* 导入                                                                 */
/* ------------------------------------------------------------------ */
function parseDocs(text) {
  // 以空行分隔多篇；单篇则整体作为一篇
  const blocks = text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  return blocks.map((b, i) => {
    const lines = b.split('\n');
    const title = lines[0].trim().slice(0, 60);
    return {
      id: `ui-${Date.now().toString(36)}-${i}`,
      title,
      text: b,
    };
  });
}

async function importDocuments(docs, { batchSize, chunkChars } = {}) {
  if (!state.embedder.ready) await loadModel();
  const bs = batchSize || Number($('in-batch').value) || 16;
  const cc = chunkChars || Number($('in-chunk').value) || 480;
  const chunks = chunkDocuments(docs, { maxChars: cc, overlap: Math.min(60, Math.floor(cc / 8)) });
  if (!chunks.length) throw new Error('没有可导入的文本');

  $('import-status').textContent = `本地向量化 0/${chunks.length}`;
  const t0 = performance.now();
  const { vectors, elapsedMs, docsPerSec } = await state.embedder.embed(
    chunks.map((c) => c.text),
    { batchSize: bs, onProgress: (d, t) => { $('import-status').textContent = `本地向量化 ${d}/${t}`; $('bar-import').style.width = `${(d / t) * 60}%`; } },
  );
  recordStage('文档向量化（浏览器本地）', elapsedMs);
  const embedTotal = performance.now() - t0;

  $('import-status').textContent = '写入 seekdb…';
  const payload = {
    modelId: state.model.id,
    dtype: state.dtype,
    documents: chunks.map((c, i) => ({ id: c.id, text: c.text, vector: vectors[i], metadata: c.metadata })),
  };
  const res = await fetch('/api/documents', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json());
  if (!res.ok) throw new Error(res.error || '写入失败');

  recordStage('写入 seekdb', res.timings.writeMs);
  recordStage('索引刷新', res.timings.refreshMs);
  recordStage('导入端到端', embedTotal + res.timings.writeMs + res.timings.refreshMs);

  state.collection = res.collection;
  state.docCount = res.count;
  $('collection-value').textContent = res.collection;
  $('docs-value').textContent = String(res.count);
  $('bar-import').style.width = '100%';
  $('import-status').textContent =
    `完成：${chunks.length} 块 / ${docsPerSec.toFixed(1)} 块每秒 · 写入 ${res.timings.writeMs.toFixed(0)}ms · 刷新 ${res.timings.refreshMs.toFixed(0)}ms`;
  return { chunks: chunks.length, ...res, embedMs: elapsedMs, docsPerSec };
}

/* ------------------------------------------------------------------ */
/* 检索                                                                 */
/* ------------------------------------------------------------------ */
function highlight(text, q) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  let html = esc(text);
  const terms = (q || '').split(/[\s,，、。？?！!]+/).filter((t) => t.length >= 2);
  for (const t of terms) {
    const re = new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    html = html.replace(re, (m) => `<mark>${m}</mark>`);
  }
  return html;
}

async function search(queryText, { topK, rrfK, rrfW } = {}) {
  if (!state.embedder.ready) await loadModel();
  const q = (queryText ?? '').trim();
  if (!q) throw new Error('查询不能为空');
  const t0 = performance.now();

  const tq = performance.now();
  const { vectors, elapsedMs: queryEmbedMs } = await state.embedder.embed([q], { batchSize: 1 });
  recordStage('查询向量化（浏览器本地）', queryEmbedMs);

  const tReq = performance.now();
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      modelId: state.model.id,
      dtype: state.dtype,
      queryText: q,
      queryVector: vectors[0],
      topK: topK || Number($('in-topk').value) || 8,
      rrf: {
        rankConstant: rrfK || Number($('in-rrf-k').value) || 60,
        rankWindowSize: rrfW || Number($('in-rrf-w').value) || 60,
      },
    }),
  }).then((r) => r.json());
  if (!res.ok) throw new Error(res.error || '检索失败');
  const roundTrip = performance.now() - tReq;

  if (res.warnings && res.warnings.length) {
    banner(res.warnings.join(' '), 'warn');
  }
  recordStage('seekdb 混合检索（数据库侧）', res.timings.seekdbMs);
  recordStage('端到端查询（提交→可展示）', performance.now() - t0);
  state.lastSql = res.sql || [];

  renderResults(res.hits, q);
  return { ...res, roundTripMs: roundTrip, queryEmbedMs, endToEndMs: performance.now() - t0 };
}

function renderResults(hits, q) {
  const box = $('results');
  box.innerHTML = '';
  if (!hits || !hits.length) {
    box.innerHTML = '<div class="empty">没有命中结果</div>';
  }
  for (const h of hits) {
    const div = document.createElement('div');
    div.className = 'hit';
    const meta = h.metadata || {};
    div.innerHTML =
      `<div class="head">`
      + `<span class="rank">${h.rank}</span>`
      + `<span class="docid">${h.id}</span>`
      + `<span>${meta.title ? escapeHtml(meta.title) : ''}</span>`
      + `<span class="score">score=${(h.score ?? 0).toFixed(6)}</span>`
      + `<span>dim=${(h.vector || []).length}</span>`
      + `</div>`
      + `<div class="body">${highlight(h.document || '', q)}</div>`;
    box.appendChild(div);
  }
  $('sql-log').textContent = state.lastSql.length
    ? state.lastSql.join('\n\n')
    : '（尚无）';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ------------------------------------------------------------------ */
/* 事件绑定                                                             */
/* ------------------------------------------------------------------ */
$('sel-model').addEventListener('change', onModelChange);
$('sel-dtype').addEventListener('change', () => {
  state.dtype = $('sel-dtype').value;
  $('model-value').textContent = `${state.model.id.split('/')[1]} · ${state.dtype}`;
});
$('btn-demo').addEventListener('click', async () => {
  const docs = await fetch('/api/demo-docs').then((r) => r.json());
  $('in-docs').value = docs.documents.map((d) => `【${d.title}】\n${d.text}`).join('\n\n');
  $('import-status').textContent = `已载入 ${docs.documents.length} 篇示例文档`;
});
$('btn-file').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', async (e) => {
  const files = [...e.target.files];
  let all = '';
  for (const f of files) all += (await f.text()) + '\n\n';
  $('in-docs').value = all.trim();
  $('import-status').textContent = `已载入 ${files.length} 个文件`;
});
$('btn-import').addEventListener('click', async () => {
  const btn = $('btn-import');
  btn.disabled = true;
  try {
    const docs = parseDocs($('in-docs').value);
    if (!docs.length) { banner('请先输入或导入文档内容', 'warn'); return; }
    const r = await importDocuments(docs);
    banner(`导入成功：${r.chunks} 个切块已写入集合 ${r.collection}（当前 ${r.count} 条）。`, 'info');
  } catch (err) {
    banner(`导入失败：${err.message}`, 'err');
  } finally {
    btn.disabled = false;
  }
});
$('btn-reset').addEventListener('click', async () => {
  const r = await fetch('/api/collection/reset', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ modelId: state.model.id, dtype: state.dtype }),
  }).then((x) => x.json());
  if (r.ok) {
    state.docCount = 0;
    $('docs-value').textContent = '0';
    $('collection-value').textContent = r.collection;
    $('results').innerHTML = '<div class="empty">集合已重置，请重新导入语料</div>';
    banner(`集合 ${r.collection} 已重置。`, 'info');
  }
});
$('btn-search').addEventListener('click', async () => {
  const btn = $('btn-search');
  btn.disabled = true;
  try {
    await search($('in-query').value);
  } catch (err) {
    banner(`检索失败：${err.message}`, 'err');
  } finally {
    btn.disabled = false;
  }
});
$('in-query').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('btn-search').click(); });

init().catch((err) => banner(`初始化失败：${err.message}`, 'err'));
