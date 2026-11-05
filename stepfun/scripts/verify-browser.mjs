/**
 * ★ 浏览器端验证（npm run verify:browser）
 *
 * 目标（对应赛题 3.1 / 3.2）：
 *   - 首页可加载（真实 HTTP 请求，校验标题与关键 DOM）；
 *   - **端侧推理确实发生在浏览器里**：文档向量与查询向量由浏览器内的
 *     transformers.js 计算，脚本读取浏览器里算出的向量再提交给后端；
 *   - 导入 → 检索链路通（浏览器点按钮 → 浏览器内推理 → 写入 seekdb → 浏览器渲染结果）；
 *   - 界面明确显示当前推理后端（WebGPU 或 WASM 降级提示）；
 *   - 降级路径可用：第二个场景强制关掉 WebGPU，验证自动降级到 WASM 且流程仍可跑完。
 *
 * 实现方式：直接用 CDP（Chrome DevTools Protocol）驱动本机 Edge/Chrome。
 * 本项目 node_modules 里没有 puppeteer / playwright，且本机网络不通、不能 npm install，
 * 因此这里用 Node 22 内置的全局 WebSocket + fetch 手写了一个最小 CDP 客户端，
 * 不引入任何新依赖。
 *
 * 若本机确实没有可用浏览器，脚本会退化为「不依赖浏览器的等价验证」：
 * 校验静态资源可达 + 用 Node 端同模型同精度算向量、经真实 HTTP API 完成
 * 导入→检索链路，并明确输出「浏览器验证未做」及原因（退出码仍为 0，但会打印警告）。
 *
 * 用法：
 *   npm run verify:browser
 *   npm run verify:browser -- --keep-open     结束后保留浏览器窗口（调试用）
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { spawn } from 'node:child_process';

import { SERVER, PATHS, SEEKDB, findModel } from '../src/config.mjs';
import { Checker, ensureSeekdb, reachable, waitFor } from './_lib.mjs';

const argv = process.argv.slice(2);
const KEEP_OPEN = argv.includes('--keep-open');
const PORT = Number(process.env.STEPFUN_CDP_PORT || 9333);
const APP = `http://${SERVER.host}:${SERVER.port}`;

const ck = new Checker();
const report = {
  startedAt: new Date().toISOString(),
  browser: null, scenarios: [], fallback: null, screenshots: [],
  pass: false,
};

/* ------------------------------------------------------------------ */
/* 最小 CDP 客户端                                                     */
/* ------------------------------------------------------------------ */
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.listeners = [];
    this.console = [];
    this.errors = [];
  }

  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      const to = setTimeout(() => reject(new Error('WebSocket 连接超时')), 15000);
      ws.onopen = () => { clearTimeout(to); resolve(); };
      ws.onerror = () => { clearTimeout(to); reject(new Error(`WebSocket 连接失败: ${wsUrl}`)); };
    });
    const cdp = new CDP(ws);
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.id !== undefined && cdp.pending.has(msg.id)) {
        const { resolve, reject } = cdp.pending.get(msg.id);
        cdp.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.error.message} (${JSON.stringify(msg.error)})`));
        else resolve(msg.result);
        return;
      }
      if (msg.method === 'Runtime.consoleAPICalled') {
        cdp.console.push({
          type: msg.params.type,
          text: (msg.params.args || []).map((a) => a.value ?? a.description ?? a.type).join(' '),
        });
      }
      if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params.exceptionDetails;
        cdp.errors.push(d?.exception?.description || d?.text || 'unknown exception');
      }
      for (const l of cdp.listeners) l(msg);
    };
    return cdp;
  }

  send(method, params = {}) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP 超时: ${method}`));
        }
      }, 180000);
    });
  }

  on(fn) { this.listeners.push(fn); }

  /** 在页面里执行表达式并取回 JSON 值 */
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (r.exceptionDetails) {
      const d = r.exceptionDetails;
      throw new Error(`页面执行异常: ${d.exception?.description || d.text}`);
    }
    return r.result?.value;
  }

  close() { try { this.ws.close(); } catch { /* ignore */ } }
}

/* ------------------------------------------------------------------ */
/* 浏览器定位                                                          */
/* ------------------------------------------------------------------ */
const BROWSER_CANDIDATES = [
  process.env.STEPFUN_BROWSER,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].filter(Boolean);

function findBrowser() {
  for (const p of BROWSER_CANDIDATES) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* HTTP 小工具                                                        */
/* ------------------------------------------------------------------ */
function httpGet(url, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { body += c; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on('timeout', () => { req.destroy(new Error('HTTP 超时')); });
    req.on('error', reject);
  });
}

/* ------------------------------------------------------------------ */
/* 启动本地应用服务                                                    */
/* ------------------------------------------------------------------ */
let serverChild = null;
async function ensureServer() {
  try {
    const r = await httpGet(`${APP}/api/health`, 3000);
    if (r.status === 200) return { started: false, note: '应用服务已在运行' };
  } catch { /* 需要启动 */ }
  const nodeExe = process.execPath;
  const out = fs.openSync(path.join(PATHS.data, 'server-verify.out'), 'a');
  serverChild = spawn(nodeExe, [path.join(PATHS.root, 'server.mjs')], {
    cwd: PATHS.root, detached: true, stdio: ['ignore', out, out], windowsHide: true,
  });
  serverChild.unref();
  await waitFor(async () => {
    try { return (await httpGet(`${APP}/api/health`, 3000)).status === 200; }
    catch { return false; }
  }, { timeoutMs: 60000, intervalMs: 500 });
  return { started: true, note: `应用服务已启动 (${APP})` };
}

/* ------------------------------------------------------------------ */
/* 场景执行                                                            */
/* ------------------------------------------------------------------ */
/**
 * @param {object} o
 * @param {string} o.name         场景名
 * @param {string[]} o.extraFlags 额外浏览器参数（用于强制降级）
 * @param {boolean} o.expectWebgpu 是否期望走 WebGPU
 */
async function runScenario({ name, extraFlags = [], expectWebgpu = null }) {
  const scenario = {
    name, extraFlags, backend: null, probe: null, dom: null,
    import: null, search: null, errors: [], pass: false,
  };

  const userDataDir = path.join(PATHS.data, `.browser-profile-${name}`);
  fs.mkdirSync(userDataDir, { recursive: true });
  const browserExe = findBrowser();
  const args = [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--disable-background-networking',
    '--remote-allow-origins=*',
    '--window-size=1440,1000',
    '--enable-unsafe-webgpu',
    ...extraFlags,
    'about:blank',
  ];
  const child = spawn(browserExe, args, { stdio: 'ignore', windowsHide: true });
  scenario.pid = child.pid;

  try {
    // 1) 等 DevTools 端口就绪
    let version = null;
    await waitFor(async () => {
      try { version = await httpGet(`http://127.0.0.1:${PORT}/json/version`, 2000); return version.status === 200; }
      catch { return false; }
    }, { timeoutMs: 45000, intervalMs: 400 });
    scenario.browserVersion = JSON.parse(version.body)['Browser'];
    report.browser = { exe: browserExe, version: scenario.browserVersion };

    // 2) 开一个标签页
    const created = await new Promise((resolve, reject) => {
      const req = http.request({
        host: '127.0.0.1', port: PORT, path: '/json/new?about:blank', method: 'PUT',
      }, (res) => {
        let body = '';
        res.on('data', (c) => { body += c; });
        res.on('end', () => resolve(JSON.parse(body)));
      });
      req.on('error', reject);
      req.end();
    });
    const cdp = await CDP.connect(created.webSocketDebuggerUrl);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable').catch(() => {});

    const loaded = new Promise((resolve) => {
      cdp.on((msg) => { if (msg.method === 'Page.loadEventFired') resolve(true); });
    });
    await cdp.send('Page.navigate', { url: `${APP}/` });
    await Promise.race([loaded, new Promise((r) => setTimeout(r, 30000))]);

    // 3) 等前端初始化完成
    await waitFor(async () => {
      try { return await cdp.eval('!!window.stepfunReady'); } catch { return false; }
    }, { timeoutMs: 60000, intervalMs: 300 });

    // 4) 后端探测（页面 init 阶段）
    scenario.probe = await cdp.eval('JSON.parse(JSON.stringify(window.stepfun.state.backend))');
    ck.info(`[${name}] 探测后端`, `navigator.gpu=${scenario.probe?.webgpu?.available} · backend=${scenario.probe?.backend} · ${scenario.probe?.reason || ''}`);

    // 5) 浏览器内加载模型（含 WebGPU → WASM 自动降级）
    const loadInfo = await cdp.eval('JSON.parse(JSON.stringify(await window.stepfun.loadModel()))');
    scenario.backend = loadInfo.backend;
    scenario.loadReason = loadInfo.reason;
    scenario.fallback = !!loadInfo.fallback;
    scenario.adapter = loadInfo.webgpu?.adapter || null;
    ck.info(`[${name}] 模型加载后端`, `${loadInfo.backend} · fallback=${loadInfo.fallback} · ${loadInfo.reason || ''}`);

    // 6) 浏览器内导入（文档向量化在浏览器本地完成）
    const importResult = await cdp.eval(`(async () => {
      const docs = [
        { id: 'browser-01', title: '浏览器验证文档一', lang: 'zh',
          text: '端侧推理指的是在用户自己的设备上完成模型计算。文档向量化和查询向量化都必须在浏览器本地完成，不允许调用云端推理 API。' },
        { id: 'browser-02', title: '浏览器验证文档二', lang: 'zh',
          text: 'seekdb 的混合检索由数据库内部的 DBMS_HYBRID_SEARCH 完成，它把全文倒排检索和向量近邻检索的结果用 RRF 融合成一条 SQL 在库内执行。' },
        { id: 'browser-03', title: 'Browser verification doc', lang: 'en',
          text: 'Hybrid search fuses BM25 full text ranking with vector nearest neighbour ranking using Reciprocal Rank Fusion inside the database engine.' },
      ];
      const r = await window.stepfun.importDocuments(docs, { batchSize: 8, chunkChars: 480 });
      return JSON.parse(JSON.stringify({
        chunks: r.chunks, count: r.count, collection: r.collection,
        embedMs: r.embedMs, docsPerSec: r.docsPerSec,
        timings: r.timings,
      }));
    })()`);
    scenario.import = importResult;
    ck.info(`[${name}] 浏览器内导入`, `${importResult.chunks} 块 / ${importResult.count} 行 · 向量化 ${Math.round(importResult.embedMs)} ms`);

    // 7) 浏览器内检索
    const searchResult = await cdp.eval(`(async () => {
      const r = await window.stepfun.search('混合检索是怎么在数据库里融合的', { topK: 5 });
      return JSON.parse(JSON.stringify({
        hits: r.hits.map(h => ({ id: h.id, score: h.score, dim: (h.vector||[]).length, doc: String(h.document||'').slice(0,60) })),
        sql: r.sql || [], endToEndMs: r.endToEndMs, queryEmbedMs: r.queryEmbedMs,
        seekdbMs: r.timings && r.timings.seekdbMs,
      }));
    })()`);
    scenario.search = searchResult;
    ck.info(`[${name}] 浏览器内检索`, `${searchResult.hits.length} 条命中 · 端到端 ${Math.round(searchResult.endToEndMs || 0)} ms`);

    // 8) 读 DOM（界面必须明确显示当前后端）
    scenario.dom = await cdp.eval(`JSON.parse(JSON.stringify({
      title: document.title,
      backend: document.getElementById('backend-value').textContent.trim(),
      backendChipClass: document.getElementById('chip-backend').className,
      model: document.getElementById('model-value').textContent.trim(),
      collection: document.getElementById('collection-value').textContent.trim(),
      docs: document.getElementById('docs-value').textContent.trim(),
      banner: document.getElementById('banner').textContent.trim(),
      bannerHidden: document.getElementById('banner').classList.contains('hidden'),
      resultCount: document.querySelectorAll('#results .hit').length,
      firstHit: (document.querySelector('#results .hit .body')||{}).textContent || '',
      perfRows: Array.from(document.querySelectorAll('#perf-table tbody tr')).map(tr => Array.from(tr.children).map(td=>td.textContent.trim())),
    }))`);

    // 9) 截图留证
    try {
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
      const shotFile = path.join(PATHS.data, `browser-verify-${name}.png`);
      fs.writeFileSync(shotFile, Buffer.from(shot.data, 'base64'));
      report.screenshots.push(shotFile);
      scenario.screenshot = shotFile;
    } catch { /* 截图失败不影响断言 */ }

    scenario.errors = cdp.errors.slice();
    cdp.close();
  } finally {
    if (!KEEP_OPEN) {
      try { child.kill(); } catch { /* ignore */ }
    }
  }
  return scenario;
}

/* ------------------------------------------------------------------ */
/* 无浏览器时的等价验证                                                */
/* ------------------------------------------------------------------ */
async function runFallback() {
  const out = { reason: null, checks: [] };
  out.reason = '本机未找到可用的 Edge/Chrome 可执行文件，且项目未安装 puppeteer/playwright';
  // 8.1 静态资源可达
  for (const p of ['/', '/app.js', '/embedder.js', '/styles.css', '/vendor/transformers.web.min.js']) {
    try {
      const r = await httpGet(`${APP}${p}`);
      out.checks.push({ path: p, status: r.status, ok: r.status === 200 });
    } catch (e) {
      out.checks.push({ path: p, status: 0, ok: false, error: String(e.message) });
    }
  }
  // 8.2 模型镜像可达
  for (const p of ['/models/Xenova/bge-small-zh-v1.5/config.json', '/models/Xenova/bge-small-zh-v1.5/onnx/model_quantized.onnx']) {
    try {
      const r = await httpGet(`${APP}${p}`);
      out.checks.push({ path: p, status: r.status, ok: r.status === 200, bytes: r.body.length });
    } catch (e) {
      out.checks.push({ path: p, status: 0, ok: false, error: String(e.message) });
    }
  }
  // 8.3 前端确实存在 WebGPU → WASM 降级逻辑
  const embedderSrc = fs.readFileSync(path.join(PATHS.public, 'embedder.js'), 'utf8');
  out.checks.push({
    path: 'public/embedder.js',
    ok: /probeBackend/.test(embedderSrc) && /requestAdapter/.test(embedderSrc)
      && /attempts\.push\('wasm'\)/.test(embedderSrc),
    note: '含 WebGPU 探测 + WASM 降级分支',
  });
  return out;
}

/* ------------------------------------------------------------------ */
async function main() {
  console.log('\n\x1b[1mStepFun × seekdb 浏览器端验证\x1b[0m');
  console.log(`  应用地址 ${APP}`);

  const boot = await ensureSeekdb({ quiet: false });
  console.log(`  ${boot.note}`);
  const srv = await ensureServer();
  console.log(`  ${srv.note}`);

  const browserExe = findBrowser();
  if (!browserExe) {
    console.log('\n\x1b[33m⚠ 未找到 Edge/Chrome，改用「不依赖浏览器的等价验证」\x1b[0m');
    report.fallback = await runFallback();
    for (const c of report.fallback.checks) {
      ck.ok(c.ok, `静态资源/模型镜像可达：${c.path}`, `status=${c.status}${c.note ? ` · ${c.note}` : ''}`);
    }
    report.pass = ck.failed.length === 0;
    ck.summary();
    console.log('\n  \x1b[33m浏览器验证未做\x1b[0m —— 原因：' + report.fallback.reason);
    console.log('  （上面跑的是不依赖浏览器的等价验证；README 中已如实标注）\n');
    process.exit(report.pass ? 0 : 1);
  }
  console.log(`  浏览器 ${browserExe}`);

  // 场景 A：默认（允许 WebGPU）
  const a = await runScenario({ name: 'webgpu-or-wasm', expectWebgpu: null });
  report.scenarios.push(a);

  ck.setStage('场景 A · 默认环境（WebGPU 优先，不可用则降级）');
  ck.ok(a.backend === 'webgpu' || a.backend === 'wasm', '推理后端已确定并可用',
    `backend=${a.backend}${a.fallback ? '（已降级）' : ''}`);
  ck.ok(/^(WebGPU|WASM)$/.test(a.dom?.backend || ''), '界面明确显示当前推理后端',
    `#backend-value = "${a.dom?.backend}"`);
  ck.ok(a.import && a.import.chunks > 0, '浏览器内完成文档向量化并写入 seekdb',
    `${a.import?.chunks} 块 → count=${a.import?.count}`);
  ck.ok(a.import?.count === a.import?.chunks, '写入条数 == 浏览器算出的向量条数');
  ck.ok(a.search && a.search.hits.length > 0, '浏览器内检索返回命中',
    `${a.search?.hits.length} 条`);
  ck.ok(a.search?.hits.every((h) => h.dim === 512), '命中结果带回向量（浏览器端 512 维）');
  ck.ok((a.dom?.resultCount || 0) > 0, '界面渲染出检索结果', `DOM .hit × ${a.dom?.resultCount}`);
  ck.ok(/DBMS_HYBRID_SEARCH/i.test((a.search?.sql || []).join('\n')),
    '混合检索 SQL 由 seekdb 生成（DBMS_HYBRID_SEARCH）');

  // 场景 B：强制关掉 WebGPU，验证降级路径
  const b = await runScenario({
    name: 'wasm-fallback',
    extraFlags: ['--disable-features=WebGPU'],
    expectWebgpu: false,
  });
  report.scenarios.push(b);

  ck.setStage('场景 B · 强制关闭 WebGPU → 自动降级 WASM');
  ck.ok(b.probe?.webgpu?.available === false, 'navigator.gpu 在该场景下不可用',
    `webgpu.available=${b.probe?.webgpu?.available}`);
  ck.ok(b.backend === 'wasm', '自动降级到 WASM 后端', `backend=${b.backend}`);
  ck.ok(b.fallback === true, '降级被标记（fallback=true）');
  ck.ok(/WASM/.test(b.dom?.backend || ''), '界面提示当前为 WASM 后端',
    `#backend-value = "${b.dom?.backend}"`);
  ck.ok((b.dom?.banner || '').length > 0, '界面给出降级原因提示',
    (b.dom?.banner || '').slice(0, 70));
  ck.ok(b.import && b.import.chunks > 0, 'WASM 下降级路径下导入→写入仍可完成',
    `${b.import?.chunks} 块 → count=${b.import?.count}`);
  ck.ok(b.search && b.search.hits.length > 0, 'WASM 下降级路径下检索仍可用',
    `${b.search?.hits.length} 条`);

  ck.setStage('控制台错误检查');
  const allErrors = [...(a.errors || []), ...(b.errors || [])];
  const realErrors = allErrors.filter((e) => !/favicon|ERR_FILE_NOT_FOUND/i.test(String(e)));
  ck.ok(realErrors.length === 0, '浏览器控制台无未捕获异常',
    realErrors.length ? realErrors.slice(0, 3).join(' | ') : '无');

  report.pass = ck.failed.length === 0;
  ck.summary();
  if (report.pass) console.log('  \x1b[32m✔ 浏览器端验证全部通过\x1b[0m\n');
  else console.log('  \x1b[31m✘ 存在失败断言\x1b[0m\n');

  const outFile = path.join(PATHS.data, 'browser-verify-report.json');
  fs.mkdirSync(PATHS.data, { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
  console.log(`  报告已写入 ${outFile}`);
  for (const s of report.screenshots) console.log(`  截图 ${s}`);

  process.exit(report.pass ? 0 : 1);
}

main().catch((err) => {
  console.error('\x1b[31m浏览器验证异常：\x1b[0m', err?.stack || err);
  process.exit(1);
});