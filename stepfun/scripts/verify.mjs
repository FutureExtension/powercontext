/**
 * ★ 核心验证脚本（npm run verify）
 *
 * 一条命令跑完「导入 → 端侧向量化 → 写入 seekdb → 刷新索引 → 混合检索 → 增量写入」全链路，
 * 并对每个关键不变量做断言。任何一条断言不通过 → 进程退出码 1。
 *
 * 断言覆盖（对应赛题验收标准）：
 *   1. 向量维度 == 模型声明维度；L2 范数 ≈ 1（normalize 生效）
 *   2. 写入 seekdb 后 count() 数量正确
 *   3. 从 seekdb 回读：原文列与写入原文逐字一致；向量列与端侧算出的向量余弦 ≈ 1
 *   4. hybridSearch 返回条数 > 0
 *   5. 检索结果里的 document 与写入原文一致
 *   6. 混合检索确实由 seekdb 完成（SQL 中出现 DBMS_HYBRID_SEARCH.GET_SQL 与 RRF 融合式）
 *   7. 增量写入 + 刷新后，新文档可被检索到，count 正确增长
 *   8. 检索质量：Recall@5 / HitRate@5 / nDCG@5（固定语料 + 固定查询集）
 *
 * 用法：
 *   npm run verify              人类可读日志
 *   npm run verify -- --json    只输出 JSON 报告
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { createEmbedder } from '../src/embedder.mjs';
import { SeekdbService, tableNameOf } from '../src/seekdb-service.mjs';
import { findModel, collectionNameFor, PATHS } from '../src/config.mjs';
import { DEMO_DOCS, chunkDocuments, EVAL_QUERIES } from '../src/corpus.mjs';
import { Checker, ensureSeekdb, cosine, norm, ms } from './_lib.mjs';

const argv = process.argv.slice(2);
const JSON_ONLY = argv.includes('--json');
const MODEL_ID = argv.includes('--model')
  ? argv[argv.indexOf('--model') + 1]
  : 'Xenova/bge-small-zh-v1.5';
const DTYPE = argv.includes('--dtype')
  ? argv[argv.indexOf('--dtype') + 1]
  : 'q8';
const TOPK = 5;

const log = (...a) => { if (!JSON_ONLY) console.log(...a); };
const report = {
  startedAt: new Date().toISOString(),
  model: null, dtype: DTYPE, collection: null, table: null,
  stages: [], timings: {}, counts: {}, quality: null,
  hybridSearchSql: [], assertions: [], pass: false,
};

const ck = new Checker();
const originalLog = console.log;
if (JSON_ONLY) console.log = () => {};

/* ------------------------------------------------------------------ */
async function main() {
  const model = findModel(MODEL_ID);
  report.model = { id: model.id, dim: model.dim, pooling: model.pooling, license: model.license };

  log(`\n\x1b[1mStepFun × seekdb 迷你知识库 —— 端到端验证\x1b[0m`);
  log(`  模型 ${model.id}（${model.dim} 维） · 精度 ${DTYPE} · 语料 ${DEMO_DOCS.length} 篇`);

  /* ---------------- 阶段 1：环境与模型加载 ---------------- */
  ck.setStage('阶段 1/8 · 环境与模型加载');
  const boot = await ensureSeekdb({ quiet: JSON_ONLY });
  ck.info('seekdb', boot.note);
  report.stages.push({ stage: 'seekdb', note: boot.note });

  const tLoad0 = performance.now();
  const emb = await createEmbedder({ modelId: model.id, dtype: DTYPE, batchSize: 16 });
  const loadMs = performance.now() - tLoad0;
  report.timings.modelLoadMs = ms(loadMs);
  ck.ok(true, '模型在本地加载成功', `dtype=${DTYPE}, ${ms(loadMs)} ms, backend=cpu(onnxruntime-node)`);
  ck.info('模型缓存目录', PATHS.modelCache);

  /* ---------------- 阶段 2：切块 ---------------- */
  ck.setStage('阶段 2/8 · 文档切分（与服务端/前端同一套规则）');
  const chunks = chunkDocuments(DEMO_DOCS);
  report.counts.sourceDocs = DEMO_DOCS.length;
  report.counts.chunks = chunks.length;
  ck.ok(chunks.length >= DEMO_DOCS.length, '每篇文档至少切出 1 个块',
    `${DEMO_DOCS.length} 篇 → ${chunks.length} 块`);
  ck.ok(chunks.every((c) => typeof c.text === 'string' && c.text.length > 0), '所有块原文非空');
  ck.ok(chunks.every((c) => c.metadata && c.metadata.doc_id), '所有块都带 doc_id 元数据（可回溯）');

  /* ---------------- 阶段 3：端侧向量化 ---------------- */
  ck.setStage('阶段 3/8 · 端侧向量化（本地推理，不经云端 API）');
  const tEmb = performance.now();
  const { vectors, elapsedMs, docsPerSec } = await emb.embed(chunks.map((c) => c.text));
  const embedWallMs = performance.now() - tEmb;
  report.timings.embedDocsMs = ms(elapsedMs);
  report.timings.embedThroughputDocsPerSec = Number(docsPerSec.toFixed(2));
  ck.ok(vectors.length === chunks.length, '向量条数 == 切块数',
    `${vectors.length} == ${chunks.length}`);
  ck.ok(vectors.every((v) => v.length === model.dim), '每个向量维度 == 模型声明维度',
    `dim=${model.dim}`);
  const norms = vectors.map(norm);
  const normOk = norms.every((n) => Math.abs(n - 1) < 1e-3);
  ck.ok(normOk, '所有向量 L2 范数 ≈ 1（normalize 生效）',
    `min=${Math.min(...norms).toFixed(6)} max=${Math.max(...norms).toFixed(6)}`);
  ck.info('向量化耗时', `${ms(elapsedMs)} ms · ${docsPerSec.toFixed(2)} 块/秒（墙上 ${ms(embedWallMs)} ms）`);

  /* ---------------- 阶段 4：seekdb 集合与写入 ---------------- */
  ck.setStage('阶段 4/8 · 写入 seekdb + 索引刷新');
  const svc = new SeekdbService();
  await svc.connect();
  const collName = collectionNameFor(model.id, DTYPE);
  const coll = await svc.resetCollection(collName, model);
  const table = tableNameOf(coll);
  report.collection = collName;
  report.table = table;
  ck.ok(true, '集合已创建（reset 后重建，保证可复现）', `${collName} → 表 ${table}`);

  const docs = chunks.map((c, i) => ({
    id: c.id, text: c.text, vector: vectors[i], metadata: c.metadata,
  }));
  const tWrite = performance.now();
  await svc.upsertDocuments(collName, docs, model);
  const writeMs = performance.now() - tWrite;
  const tFlush = performance.now();
  await svc.refreshIndex(collName);
  const refreshMs = performance.now() - tFlush;
  report.timings.writeMs = ms(writeMs);
  report.timings.refreshIndexMs = ms(refreshMs);

  const count = await svc.count(collName);
  report.counts.rows = count;
  ck.ok(count === docs.length, 'seekdb count() == 写入条数',
    `${count} == ${docs.length}`);
  ck.info('写入/刷新耗时', `write=${ms(writeMs)} ms, refresh=${ms(refreshMs)} ms`);

  /* ---------------- 阶段 5：回读核对 ---------------- */
  ck.setStage('阶段 5/8 · 从 seekdb 回读核对（原文列 + 向量列）');
  const rows = await svc.rawSql(
    `SELECT _id, document, metadata, embedding FROM \`${table}\` ORDER BY _id`,
  );
  ck.ok(rows.length === docs.length, '回读行数 == 写入条数', `${rows.length} == ${docs.length}`);

  const byId = new Map(docs.map((d) => [d.id, d]));
  let textMismatch = 0;
  let vecMismatch = 0;
  let minCos = 1;
  for (const r of rows) {
    const id = Buffer.isBuffer(r._id) ? r._id.toString('utf8') : String(r._id);
    const origin = byId.get(id);
    if (!origin) { textMismatch++; continue; }
    if (String(r.document) !== origin.text) textMismatch++;
    let stored = r.embedding;
    if (typeof stored === 'string') { try { stored = JSON.parse(stored); } catch { /* 原样 */ } }
    if (!Array.isArray(stored) || stored.length !== origin.vector.length) { vecMismatch++; continue; }
    const c = cosine(stored, origin.vector);
    if (c < minCos) minCos = c;
    if (c < 0.999) vecMismatch++;
  }
  report.counts.textMismatches = textMismatch;
  report.counts.vectorMismatches = vecMismatch;
  report.counts.minStoredVectorCosine = Number(minCos.toFixed(6));
  ck.ok(textMismatch === 0, '原文列与写入原文逐字一致', `不一致 ${textMismatch} 行`);
  ck.ok(vecMismatch === 0, '向量列与端侧算出的向量一致（余弦 ≥ 0.999）',
    `不一致 ${vecMismatch} 行, 最小余弦 ${minCos.toFixed(6)}`);

  /* ---------------- 阶段 6：混合检索 ---------------- */
  ck.setStage('阶段 6/8 · seekdb 混合检索（数据库侧融合）');
  const probe = 'RRF 融合算法是怎么工作的';
  const tQ = performance.now();
  const qv = (await emb.embed([probe], { batchSize: 1 })).vectors[0];
  const queryEmbedMs = performance.now() - tQ;
  report.timings.queryEmbedMs = ms(queryEmbedMs);

  const search = await svc.hybridSearch(collName, { queryText: probe, queryVector: qv, topK: TOPK });
  report.timings.seekdbSearchMs = ms(search.elapsedMs);
  report.hybridSearchSql = search.sqls.map((s) => s.sql);

  ck.ok(search.hits.length > 0, 'hybridSearch 返回条数 > 0', `${search.hits.length} 条`);
  let hitTextBad = 0;
  for (const h of search.hits) {
    const origin = byId.get(h.id);
    if (!origin || origin.text !== h.document) hitTextBad++;
  }
  ck.ok(hitTextBad === 0, '检索结果中的原文与写入原文一致', `不一致 ${hitTextBad} 条`);

  const sqlJoined = search.sqls.map((s) => s.sql).join('\n');
  const byDb = /DBMS_HYBRID_SEARCH/i.test(sqlJoined);
  const rrfInSql = /_keyword_rank/i.test(sqlJoined) && /_semantic_rank/i.test(sqlJoined);
  ck.ok(byDb, '混合检索由 seekdb 完成（SQL 中出现 DBMS_HYBRID_SEARCH）',
    byDb ? 'DBMS_HYBRID_SEARCH.GET_SQL' : '未找到');
  ck.ok(rrfInSql, '融合在数据库侧完成（同一 SQL 内含全文 rank + 向量 rank 的 RRF 融合式）');
  ck.info('检索耗时', `${ms(search.elapsedMs)} ms（seekdb 侧）`);
  for (const h of search.hits.slice(0, 5)) {
    ck.info(`#${h.rank}`, `${h.id}  score=${h.score === null ? 'n/a' : h.score.toFixed(6)}  ${String(h.document).slice(0, 46).replace(/\n/g, ' ')}…`);
  }

  // 6b. 危险关键字降级路径：查询文本里出现数据库保留字（CALL 等）时，
  //     seekdb-js 客户端会拒绝执行生成的 SQL；数据层应只对全文通道做安全降级并重试。
  const kwQuery = '数据库索引刷新 call dbms_index_manager';
  const kwVec = (await emb.embed([kwQuery], { batchSize: 1 })).vectors[0];
  const kwRes = await svc.hybridSearch(collName, { queryText: kwQuery, queryVector: kwVec, topK: 3 });
  ck.ok(kwRes.hits.length > 0, '查询文本含数据库保留字时仍可完成混合检索（全文通道安全降级）',
    `命中 ${kwRes.hits.length} 条`);
  ck.ok((kwRes.warnings || []).length === 1, '降级时给出明确提示（warnings 非空）',
    kwRes.warnings?.[0] ? kwRes.warnings[0].slice(0, 72) + '…' : '无');

  /* ---------------- 阶段 7：增量写入 ---------------- */
  ck.setStage('阶段 7/8 · 增量写入 + 索引刷新后可见性');
  const incText = '增量写入验证文档：海王星是一颗位于太阳系外围的冰巨星。它的平均直径约 49244 公里，质量约为地球的 17 倍，表面大气以氢和氦为主。';
  const incChunks = chunkDocuments([{ id: 'inc-01', title: '增量文档', lang: 'zh', text: incText }]);
  const incVec = (await emb.embed([incChunks[0].text])).vectors[0];
  await svc.upsertDocuments(collName, [{
    id: incChunks[0].id, text: incChunks[0].text, vector: incVec, metadata: incChunks[0].metadata,
  }], model);
  await svc.refreshIndex(collName);
  const count2 = await svc.count(collName);
  report.counts.rowsAfterIncremental = count2;
  ck.ok(count2 === docs.length + 1, '增量写入后 count 正确增长',
    `${count2} == ${docs.length} + 1`);

  const incSearch = await svc.hybridSearch(collName, {
    queryText: '海王星 冰巨星 直径',
    queryVector: (await emb.embed(['海王星 冰巨星 直径'])).vectors[0],
    topK: 5,
  });
  const found = incSearch.hits.some((h) => h.id === incChunks[0].id);
  ck.ok(found, '刷新后新增文档可被检索到', found ? '命中' : '未命中');
  ck.info('增量文档检索排名', String(incSearch.hits.findIndex((h) => h.id === incChunks[0].id) + 1));

  /* ---------------- 阶段 8：检索质量 ---------------- */
  ck.setStage('阶段 8/8 · 检索质量（固定语料 + 固定查询集）');
  const K = 5;
  let recallSum = 0, hitSum = 0, ndcgSum = 0;
  for (const q of EVAL_QUERIES) {
    const v = (await emb.embed([q.query], { batchSize: 1 })).vectors[0];
    const r = await svc.hybridSearch(collName, { queryText: q.query, queryVector: v, topK: K });
    const rel = new Set(q.relevant);
    const gains = r.hits.map((h) => {
      const did = h.metadata?.doc_id || String(h.id).split('#')[0];
      return rel.has(did) ? 1 : 0;
    });
    const retrievedRel = new Set(r.hits
      .filter((h, i) => gains[i] === 1)
      .map((h) => h.metadata?.doc_id || String(h.id).split('#')[0]));
    recallSum += retrievedRel.size / rel.size;
    hitSum += gains.some((g) => g === 1) ? 1 : 0;
    let dcg = 0;
    gains.forEach((g, i) => { if (g) dcg += 1 / Math.log2(i + 2); });
    let idcg = 0;
    for (let i = 0; i < Math.min(K, rel.size); i++) idcg += 1 / Math.log2(i + 2);
    ndcgSum += idcg > 0 ? dcg / idcg : 0;
  }
  const n = EVAL_QUERIES.length;
  report.quality = {
    topK: K, queries: n,
    recallAtK: Number((recallSum / n).toFixed(4)),
    hitRateAtK: Number((hitSum / n).toFixed(4)),
    ndcgAtK: Number((ndcgSum / n).toFixed(4)),
  };
  ck.ok(report.quality.recallAtK > 0, `Recall@${K} > 0`,
    `Recall@${K}=${report.quality.recallAtK}  HitRate@${K}=${report.quality.hitRateAtK}  nDCG@${K}=${report.quality.ndcgAtK}  (${n} 条查询)`);

  await svc.close();

  /* ---------------- 汇总 ---------------- */
  const allPass = ck.summary();
  report.assertions = ck.items;
  report.pass = allPass;
  report.finishedAt = new Date().toISOString();
  report.timings.totalMs = ms(
    report.timings.modelLoadMs + report.timings.embedDocsMs
    + report.timings.writeMs + report.timings.refreshIndexMs
    + report.timings.queryEmbedMs + report.timings.seekdbSearchMs,
  );

  const outFile = path.join(PATHS.data, 'verify-report.json');
  fs.mkdirSync(PATHS.data, { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
  log(`\n  验证报告已写入 ${outFile}`);
  log(`  总计 ${report.timings.totalMs} ms（不含质量评测循环）`);

  console.log = originalLog;
  if (JSON_ONLY) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`  ${allPass ? '\x1b[32m✔ 全部断言通过\x1b[0m' : '\x1b[31m✘ 存在失败断言\x1b[0m'}`);
    console.log('');
  }
  process.exit(allPass ? 0 : 1);
}

main().catch((err) => {
  console.log = originalLog;
  console.error('\n\x1b[31m验证脚本异常终止：\x1b[0m', err?.stack || err);
  process.exit(1);
});