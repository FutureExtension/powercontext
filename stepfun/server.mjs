/**
 * StepFun 迷你知识库 —— 本地服务
 *
 * 职责边界（对应赛题 2.1 / 2.3）：
 *  - 前端（浏览器）负责：加载模型、文档向量化、查询向量化 —— 全部在用户设备本地完成；
 *  - 后端（本文件）只做两件事：静态资源托管 + 把「已经在浏览器算好的向量」写进 seekdb，
 *    并调用 seekdb 的 hybridSearch 完成混合检索。
 *  - 后端 **不做任何** embedding 计算，绝不回放服务端预计算的向量或结果。
 */
import express from 'express';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import net from 'node:net';

import { PATHS, SERVER, SEEKDB, MODELS, findModel, collectionNameFor } from './src/config.mjs';
import { SeekdbService, tableNameOf } from './src/seekdb-service.mjs';
import { DEMO_DOCS } from './src/corpus.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: '64mb' }));

// 跨源隔离：让浏览器启用 SharedArrayBuffer，WASM 后端才能开多线程（显著提升吞吐）。
// COEP 用 credentialless，模型走本地 /models 镜像（同源），仍保留 HF CDN 兜底能力。
app.use((_req, res, next) => {
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Cross-Origin-Embedder-Policy', 'credentialless');
  next();
});

/* ------------------------------------------------------------------ */
/* 静态资源                                                             */
/* ------------------------------------------------------------------ */
const VENDOR_FILES = {
  '/vendor/transformers.web.min.js': path.join(
    PATHS.nodeModules, '@huggingface', 'transformers', 'dist', 'transformers.web.min.js'),
};
const ORT_FILES = {
  '/vendor/ort/ort-wasm-simd-threaded.asyncify.mjs': path.join(
    PATHS.nodeModules, 'onnxruntime-web', 'dist', 'ort-wasm-simd-threaded.asyncify.mjs'),
  '/vendor/ort/ort-wasm-simd-threaded.asyncify.wasm': path.join(
    PATHS.nodeModules, 'onnxruntime-web', 'dist', 'ort-wasm-simd-threaded.asyncify.wasm'),
};

app.get('/vendor/transformers.web.min.js', (_req, res) => {
  const f = VENDOR_FILES['/vendor/transformers.web.min.js'];
  if (!fs.existsSync(f)) return res.status(404).send('transformers.web.min.js not found');
  res.type('application/javascript');
  res.sendFile(f);
});
for (const [route, file] of Object.entries(ORT_FILES)) {
  app.get(route, (_req, res) => {
    if (!fs.existsSync(file)) return res.status(404).send('not found');
    res.type(file.endsWith('.wasm') ? 'application/wasm' : 'application/javascript');
    res.sendFile(file);
  });
}
// 本地模型镜像：/models/<org>/<name>/<file>
app.use('/models', express.static(PATHS.modelCache, {
  fallthrough: true,
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('.onnx')) res.type('application/octet-stream');
  },
}));
app.use(express.static(PATHS.public, { extensions: ['html'] }));

/* ------------------------------------------------------------------ */
/* seekdb                                                              */
/* ------------------------------------------------------------------ */
const db = new SeekdbService();

function seekdbReachable(port = SEEKDB.port, host = SEEKDB.host) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    const done = (ok) => { sock.destroy(); resolve(ok); };
    sock.setTimeout(1500);
    sock.once('connect', () => done(true));
    sock.once('timeout', () => done(false));
    sock.once('error', () => done(false));
    sock.connect(port, host);
  });
}

let seekdbChild = null;
async function ensureSeekdbRunning() {
  if (await seekdbReachable()) {
    console.log(`[seekdb] 已连接 ${SEEKDB.host}:${SEEKDB.port}`);
    return { started: false };
  }
  if (!fs.existsSync(SEEKDB.exe)) {
    console.warn(`[seekdb] 找不到可执行文件 ${SEEKDB.exe}，请先自行启动 seekdb server。`);
    return { started: false };
  }
  fs.mkdirSync(SEEKDB.baseDir, { recursive: true });
  console.log(`[seekdb] 启动本地 server: ${SEEKDB.exe} --base-dir ${SEEKDB.baseDir} --port ${SEEKDB.port}`);
  seekdbChild = spawn(SEEKDB.exe,
    ['--base-dir', SEEKDB.baseDir, '--nodaemon', '--port', String(SEEKDB.port)],
    { detached: false, stdio: 'ignore', windowsHide: true });
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (await seekdbReachable()) {
      console.log(`[seekdb] 启动完成 ${SEEKDB.host}:${SEEKDB.port}`);
      return { started: true };
    }
  }
  throw new Error('seekdb 启动超时');
}

/* ------------------------------------------------------------------ */
/* API                                                                 */
/* ------------------------------------------------------------------ */
app.get('/api/health', async (_req, res) => {
  const reachable = await seekdbReachable();
  let collections = [];
  let connected = false;
  try {
    await db.connect();
    connected = true;
    collections = await db.listCollections();
  } catch (err) {
    collections = [`ERROR: ${err.message}`];
  }
  res.json({
    ok: true,
    seekdb: { host: SEEKDB.host, port: SEEKDB.port, database: SEEKDB.database, reachable, connected },
    models: MODELS.map((m) => ({
      id: m.id, label: m.label, dim: m.dim, dtypes: m.dtypes,
      defaultDtype: m.defaultDtype, pooling: m.pooling, license: m.license,
    })),
    collections,
    modelCache: PATHS.modelCache,
    ortLocal: Object.keys(ORT_FILES),
  });
});

app.get('/api/demo-docs', (_req, res) => res.json({ documents: DEMO_DOCS }));

/** 重置（清空并重建）集合 —— 用于「集合状态管理」 */
app.post('/api/collection/reset', async (req, res) => {
  try {
    const { modelId, dtype } = req.body || {};
    const model = findModel(modelId);
    const d = dtype || model.defaultDtype;
    const name = collectionNameFor(model.id, d);
    const t0 = performance.now();
    await db.resetCollection(name, model);
    res.json({ ok: true, collection: name, model: model.id, dtype: d, elapsedMs: performance.now() - t0 });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/**
 * 写入文档：向量由浏览器算好后随请求带上来，服务端只负责落库 + 刷新索引。
 */
app.post('/api/documents', async (req, res) => {
  try {
    const { modelId, dtype, documents, refresh = true } = req.body || {};
    const model = findModel(modelId);
    const d = dtype || model.defaultDtype;
    const name = collectionNameFor(model.id, d);
    if (!Array.isArray(documents) || documents.length === 0) {
      return res.status(400).json({ ok: false, error: 'documents 不能为空' });
    }
    const rows = documents.map((doc, i) => {
      const vector = doc.vector;
      if (!Array.isArray(vector) || vector.length !== model.dim) {
        throw new Error(`第 ${i} 条文档向量维度非法：期望 ${model.dim}，实际 ${vector?.length}`);
      }
      return {
        id: String(doc.id),
        text: String(doc.text ?? ''),
        vector,
        metadata: { ...(doc.metadata || {}), model: model.id, dtype: d },
      };
    });

    const tWrite = performance.now();
    await db.upsertDocuments(name, rows, model);
    const writeMs = performance.now() - tWrite;

    let refreshMs = 0;
    if (refresh) {
      const tRefresh = performance.now();
      await db.refreshIndex(name);
      refreshMs = performance.now() - tRefresh;
    }

    const count = await db.count(name);
    res.json({
      ok: true, collection: name, written: rows.length, count,
      timings: { writeMs: Number(writeMs.toFixed(2)), refreshMs: Number(refreshMs.toFixed(2)) },
    });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/**
 * 混合检索：全文条件 + 查询向量一起交给 seekdb，由 seekdb 内部 DBMS_HYBRID_SEARCH 融合。
 * 客户端不做任何两路结果的自行拼合。
 */
app.post('/api/search', async (req, res) => {
  try {
    const { modelId, dtype, queryText, queryVector, topK = 10, rrf } = req.body || {};
    const model = findModel(modelId);
    const d = dtype || model.defaultDtype;
    const name = collectionNameFor(model.id, d);
    if (!Array.isArray(queryVector) || queryVector.length !== model.dim) {
      return res.status(400).json({ ok: false, error: `queryVector 维度必须为 ${model.dim}` });
    }
    const result = await db.hybridSearch(name, {
      queryText: String(queryText ?? ''),
      queryVector,
      topK: Number(topK),
      rrf,
    });
    res.json({
      ok: true,
      collection: name,
      hits: result.hits,
      timings: { seekdbMs: Number(result.elapsedMs.toFixed(2)) },
      sql: result.sqls.map((s) => s.sql),
      rrf: result.rrf,
      warnings: result.warnings || [],
    });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/** 读取集合里的原始行（校验「原文 / 向量」确实落在 seekdb 里） */
app.get('/api/collection/:name/rows', async (req, res) => {
  try {
    const name = req.params.name;
    const collection = await db.getCollection(name);
    const table = tableNameOf(collection);
    const rows = await db.rawSql(
      `SELECT _id, document, metadata, embedding FROM \`${table}\` ORDER BY _id LIMIT 200`,
    );
    res.json({
      ok: true, table,
      rows: rows.map((r) => ({
        id: Buffer.isBuffer(r._id) ? r._id.toString('utf8') : String(r._id),
        document: r.document,
        metadata: typeof r.metadata === 'string' ? JSON.parse(r.metadata) : r.metadata,
        embedding: typeof r.embedding === 'string' ? JSON.parse(r.embedding) : r.embedding,
      })),
    });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/** 原始 SQL（只读校验用） */
app.post('/api/sql', async (req, res) => {
  try {
    const { sql, params } = req.body || {};
    if (!/^\s*(select|desc|show|explain)\b/i.test(sql || '')) {
      return res.status(400).json({ ok: false, error: '仅允许只读语句' });
    }
    const rows = await db.rawSql(sql, params);
    res.json({ ok: true, rows });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

/** 模型文件体积（量化前后对比的数据来源） */
app.get('/api/model-files', async (_req, res) => {
  const out = {};
  for (const m of MODELS) {
    const dir = path.join(PATHS.modelCache, m.id);
    const files = {};
    if (fs.existsSync(dir)) {
      const walk = (base, rel = '') => {
        for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
          const full = path.join(base, entry.name);
          const relPath = rel ? `${rel}/${entry.name}` : entry.name;
          if (entry.isDirectory()) walk(full, relPath);
          else files[relPath] = fs.statSync(full).size;
        }
      };
      walk(dir);
    }
    out[m.id] = files;
  }
  res.json({ ok: true, cacheDir: PATHS.modelCache, files: out });
});

/* ------------------------------------------------------------------ */
/* 启动                                                                */
/* ------------------------------------------------------------------ */
async function main() {
  await ensureSeekdbRunning();
  try {
    await db.connect();
  } catch (err) {
    console.error('[seekdb] 连接失败：', err.message);
  }
  app.listen(SERVER.port, SERVER.host, () => {
    console.log(`\n  StepFun 迷你知识库已启动`);
    console.log(`  ➜  应用地址 : http://${SERVER.host}:${SERVER.port}/`);
    console.log(`  ➜  seekdb   : ${SEEKDB.host}:${SEEKDB.port} (db=${SEEKDB.database})`);
    console.log(`  ➜  模型缓存 : ${PATHS.modelCache}\n`);
  });
}

const shutdown = async () => {
  await db.close().catch(() => {});
  if (seekdbChild) { try { seekdbChild.kill(); } catch { /* ignore */ } }
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

