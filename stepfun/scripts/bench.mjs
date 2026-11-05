/**
 * 分阶段性能基准（npm run bench）
 *
 * 输出 JSON，阶段划分与赛题 3.2「分阶段计时」一致：
 *   modelFetchMs   —— 模型文件获取（本地缓存命中时＝读盘时间；冷下载需联网，本机未测）
 *   modelLoadMs    —— 模型加载 / 推理会话初始化
 *   documentEmbedMs—— 文档向量化（端侧推理）
 *   writeMs        —— 写入 seekdb
 *   refreshIndexMs —— 索引刷新
 *   queryEmbedMs   —— 查询向量化
 *   seekdbSearchMs —— seekdb 混合检索（数据库侧）
 *   totalMs        —— 以上之和
 *   endToEndQueryMs—— 用户提交查询 → 结果可展示（查询向量化 + 检索 + 序列化）
 *
 * 重复测量的阶段一律给中位数（median），并保留全部原始样本。
 *
 * 用法：
 *   npm run bench                    默认模型 / q8 / batch=16
 *   npm run bench -- --all           额外对比 fp32 / fp16 / q8（体积·吞吐·检索延迟·质量）
 *   npm run bench -- --batch         额外做 batch size 扫描（1/4/8/16/32/64）
 *   npm run bench -- --json          只输出 JSON
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

import { createEmbedder } from '../src/embedder.mjs';
import { SeekdbService, tableNameOf } from '../src/seekdb-service.mjs';
import { findModel, collectionNameFor, PATHS } from '../src/config.mjs';
import { DEMO_DOCS, chunkDocuments, EVAL_QUERIES } from '../src/corpus.mjs';
import { Checker, ensureSeekdb, median, percentile, ms } from './_lib.mjs';

const argv = process.argv.slice(2);
const JSON_ONLY = argv.includes('--json');
const ALL_DTYPES = argv.includes('--all');
const BATCH_SWEEP = argv.includes('--batch');
const arg = (name, def) => (argv.includes(name) ? argv[argv.indexOf(name) + 1] : def);

const MODEL_ID = arg('--model', 'Xenova/bge-small-zh-v1.5');
const DTYPE = arg('--dtype', 'q8');
const BATCH = Number(arg('--batch-size', '16'));
const REPEAT = Number(arg('--repeat', '5'));
const TOPK = 5;

const log = (...a) => { if (!JSON_ONLY) console.log(...a); };

const report = {
  meta: {
    startedAt: new Date().toISOString(),
    node: process.version,
    platform: `${process.platform} ${process.arch}`,
    cpu: os.cpus()[0]?.model || 'unknown',
    cpuCount: os.cpus().length,
    modelId: MODEL_ID,
    dtype: DTYPE,
    batchSize: BATCH,
    repeat: REPEAT,
    corpus: { docs: DEMO_DOCS.length, source: 'src/corpus.mjs DEMO_DOCS' },
    note: 'Node 端 onnxruntime-node（CPU）口径；浏览器端 WebGPU/WASM 数据见 docs/performance.md',
  },
  stages: {},
  throughput: {},
  latency: {},
  samples: {},
  comparison: null,
  batchSweep: null,
};


const ck = new Checker();

/** 计时小工具：返回 { ms, samples } */
async function timed(fn, repeat) {
  const samples = [];
  let last;
  for (let i = 0; i < repeat; i++) {
    const t = performance.now();
    last = await fn(i);
    samples.push(performance.now() - t);
  }
  return { ms: ms(median(samples)), samples: samples.map(ms), last };
}

/** 读模型权重文件（模拟「获取模型」这一步在本地缓存命中时的耗时） */
function readModelBytes(modelId, dtype) {
  const rel = {
    fp32: 'onnx/model.onnx', fp16: 'onnx/model_fp16.onnx', q8: 'onnx/model_quantized.onnx',
  }[dtype] || 'onnx/model_quantized.onnx';
  const p = path.join(PATHS.modelCache, modelId, rel);
  const buf = fs.readFileSync(p);
  return { bytes: buf.length, file: p };
}

async function runConfig(model, dtype, { batchSize, repeat, withQuality }) {
  const out = { dtype, batchSize };

  // --- 模型获取 + 加载 ---
  const tFetch = performance.now();
  const fetched = readModelBytes(model.id, dtype);
  const fetchMs = performance.now() - tFetch;
  const tLoad = performance.now();
  const emb = await createEmbedder({ modelId: model.id, dtype, batchSize });
  const loadMs = performance.now() - tLoad;
  out.modelFetchMs = ms(fetchMs);
  out.modelBytes = fetched.bytes;
  out.modelLoadMs = ms(loadMs);

  // --- 文档向量化 ---
  const chunks = chunkDocuments(DEMO_DOCS);
  // 预热一次：排除首次推理的懒初始化 / 内存分配开销，计时只统计预热后的请求
  await emb.embed(chunks.slice(0, Math.min(batchSize, chunks.length)).map((c) => c.text), { batchSize });
  const embRun = await timed(async () => {
    const r = await emb.embed(chunks.map((c) => c.text), { batchSize });
    return r;
  }, Math.min(repeat, 3));
  const { vectors } = embRun.last;
  out.chunks = chunks.length;
  out.documentEmbedMs = embRun.ms;
  out.embedSamplesMs = embRun.samples;
  out.embedThroughputDocsPerSec = Number((chunks.length / (embRun.ms / 1000)).toFixed(2));

  // --- 写入 + 索引刷新 ---
  const svc = new SeekdbService();
  await svc.connect();
  const collName = collectionNameFor(model.id, dtype);
  const coll = await svc.resetCollection(collName, model);
  out.collection = collName;
  out.table = tableNameOf(coll);
  const docs = chunks.map((c, i) => ({
    id: c.id, text: c.text, vector: vectors[i], metadata: c.metadata,
  }));
  const tWrite = performance.now();
  await svc.upsertDocuments(collName, docs, model);
  const writeMs = performance.now() - tWrite;
  const tRefresh = performance.now();
  await svc.refreshIndex(collName);
  const refreshMs = performance.now() - tRefresh;
  out.writeMs = ms(writeMs);
  out.refreshIndexMs = ms(refreshMs);
  out.rows = await svc.count(collName);

  // --- 查询向量化 ---
  const qTexts = EVAL_QUERIES.map((q) => q.query);
  const qvAll = (await emb.embed(qTexts, { batchSize })).vectors;
  const qRun = await timed(async (i) => {
    const t = performance.now();
    await emb.embed([qTexts[i % qTexts.length]], { batchSize: 1 });
    return null;
  }, repeat);
  out.queryEmbedMs = qRun.ms;
  out.queryEmbedSamplesMs = qRun.samples;

  // --- seekdb 混合检索 ---
  const sRun = await timed(async (i) => {
    const q = EVAL_QUERIES[i % EVAL_QUERIES.length];
    const r = await svc.hybridSearch(collName, {
      queryText: q.query, queryVector: qvAll[i % qvAll.length], topK: TOPK,
    });
    return r;
  }, repeat);
  out.seekdbSearchMs = sRun.ms;
  out.seekdbSearchSamplesMs = sRun.samples;

  // --- 端到端（查询向量化 + 检索） ---
  const e2e = qRun.samples.map((qms, i) => qms + sRun.samples[i]);
  out.endToEndQueryMs = ms(median(e2e));
  out.endToEndQueryP95Ms = ms(percentile(e2e, 0.95));

  // --- 检索质量 ---
  if (withQuality) {
    let recall = 0, hit = 0, ndcg = 0;
    for (let i = 0; i < EVAL_QUERIES.length; i++) {
      const q = EVAL_QUERIES[i];
      const r = await svc.hybridSearch(collName, {
        queryText: q.query, queryVector: qvAll[i], topK: TOPK,
      });
      const rel = new Set(q.relevant);
      const gains = r.hits.map((h) => (rel.has(h.metadata?.doc_id) ? 1 : 0));
      const got = new Set(r.hits.filter((h, k) => gains[k] === 1).map((h) => h.metadata?.doc_id));
      recall += got.size / rel.size;
      hit += gains.some((g) => g === 1) ? 1 : 0;
      let dcg = 0;
      gains.forEach((g, k) => { if (g) dcg += 1 / Math.log2(k + 2); });
      let idcg = 0;
      for (let k = 0; k < Math.min(TOPK, rel.size); k++) idcg += 1 / Math.log2(k + 2);
      ndcg += idcg > 0 ? dcg / idcg : 0;
    }
    const n = EVAL_QUERIES.length;
    out.quality = {
      topK: TOPK,
      queries: n,
      recallAtK: Number((recall / n).toFixed(4)),
      hitRateAtK: Number((hit / n).toFixed(4)),
      ndcgAtK: Number((ndcg / n).toFixed(4)),
    };
  }

  await svc.close();
  return out;
}

async function main() {
  const model = findModel(MODEL_ID);
  log(`\n\x1b[1mStepFun × seekdb 分阶段性能基准\x1b[0m`);
  log(`  设备：${report.meta.cpu} × ${report.meta.cpuCount} · Node ${process.version}`);
  log(`  模型：${model.id} · 精度 ${DTYPE} · batch=${BATCH} · 重复 ${REPEAT} 次取中位数`);
  log(`  语料：${DEMO_DOCS.length} 篇 / ${chunkDocuments(DEMO_DOCS).length} 块`);

  const boot = await ensureSeekdb({ quiet: JSON_ONLY });
  log(`  ${boot.note}`);

  log(`\n▸ 主配置（${DTYPE}）`);
  const main_ = await runConfig(model, DTYPE, { batchSize: BATCH, repeat: REPEAT, withQuality: true });
  report.stages = {
    modelFetchMs: main_.modelFetchMs,
    modelLoadMs: main_.modelLoadMs,
    documentEmbedMs: main_.documentEmbedMs,
    writeMs: main_.writeMs,
    refreshIndexMs: main_.refreshIndexMs,
    queryEmbedMs: main_.queryEmbedMs,
    seekdbSearchMs: main_.seekdbSearchMs,
    totalMs: ms(
      main_.modelFetchMs + main_.modelLoadMs + main_.documentEmbedMs
      + main_.writeMs + main_.refreshIndexMs + main_.queryEmbedMs + main_.seekdbSearchMs,
    ),
  };
  report.throughput = {
    chunks: main_.chunks,
    embedDocsPerSec: main_.embedThroughputDocsPerSec,
  };
  report.latency = {
    endToEndQueryMs: main_.endToEndQueryMs,
    endToEndQueryP95Ms: main_.endToEndQueryP95Ms,
  };
  report.samples = {
    documentEmbedMs: main_.embedSamplesMs,
    queryEmbedMs: main_.queryEmbedSamplesMs,
    seekdbSearchMs: main_.seekdbSearchSamplesMs,
  };
  report.quality = main_.quality;
  report.main = main_;

  log(`  模型获取 ${report.stages.modelFetchMs} ms（本地缓存命中，${(main_.modelBytes / 1048576).toFixed(2)} MiB）`);
  log(`  模型加载 ${report.stages.modelLoadMs} ms`);
  log(`  文档向量化 ${report.stages.documentEmbedMs} ms  (${report.throughput.embedDocsPerSec} 块/秒)`);
  log(`  写入 ${report.stages.writeMs} ms · 索引刷新 ${report.stages.refreshIndexMs} ms`);
  log(`  查询向量化 ${report.stages.queryEmbedMs} ms · seekdb 检索 ${report.stages.seekdbSearchMs} ms`);
  log(`  端到端查询中位数 ${report.latency.endToEndQueryMs} ms (P95 ${report.latency.endToEndQueryP95Ms} ms)`);
  log(`  质量 Recall@${TOPK}=${main_.quality.recallAtK} HitRate@${TOPK}=${main_.quality.hitRateAtK} nDCG@${TOPK}=${main_.quality.ndcgAtK}`);

  if (ALL_DTYPES) {
    log(`\n▸ 精度对比（fp32 / fp16 / q8）`);
    const results = [];
    for (const dt of ['fp32', 'fp16', 'q8']) {
      const r = await runConfig(model, dt, { batchSize: BATCH, repeat: REPEAT, withQuality: true });
      results.push(r);
      log(`  ${dt.padEnd(5)} 体积 ${(r.modelBytes / 1048576).toFixed(2)} MiB · 加载 ${r.modelLoadMs} ms · `
        + `向量化 ${r.documentEmbedMs} ms (${r.embedThroughputDocsPerSec} 块/秒) · 检索 ${r.seekdbSearchMs} ms · `
        + `端到端 ${r.endToEndQueryMs} ms · Recall@${TOPK}=${r.quality.recallAtK} nDCG@${TOPK}=${r.quality.ndcgAtK}`);
    }
    const base = results.find((r) => r.dtype === 'fp32');
    report.comparison = results.map((r) => ({
      dtype: r.dtype,
      modelBytes: r.modelBytes,
      modelMiB: Number((r.modelBytes / 1048576).toFixed(2)),
      compressionRatio: Number((base.modelBytes / r.modelBytes).toFixed(4)),
      modelLoadMs: r.modelLoadMs,
      documentEmbedMs: r.documentEmbedMs,
      embedDocsPerSec: r.embedThroughputDocsPerSec,
      writeMs: r.writeMs,
      refreshIndexMs: r.refreshIndexMs,
      queryEmbedMs: r.queryEmbedMs,
      seekdbSearchMs: r.seekdbSearchMs,
      endToEndQueryMs: r.endToEndQueryMs,
      recallAtK: r.quality.recallAtK,
      hitRateAtK: r.quality.hitRateAtK,
      ndcgAtK: r.quality.ndcgAtK,
    }));
  }

  if (BATCH_SWEEP) {
    log(`\n▸ batch size 扫描（同一个 embedder 实例，只改变每次送入的批大小；已预热）`);
    const sweepEmb = await createEmbedder({ modelId: model.id, dtype: DTYPE, batchSize: 1 });
    const sweepTexts = chunkDocuments(DEMO_DOCS).map((c) => c.text);
    await sweepEmb.embed(sweepTexts.slice(0, 1), { batchSize: 1 }); // 预热
    const sweep = [];
    for (const b of [1, 4, 8, 16, 32, 64]) {
      const samples = [];
      for (let i = 0; i < 5; i++) {
        const t0 = performance.now();
        await sweepEmb.embed(sweepTexts, { batchSize: b });
        samples.push(performance.now() - t0);
      }
      const med = median(samples);
      const perSec = Number((sweepTexts.length / (med / 1000)).toFixed(2));
      sweep.push({
        batchSize: b,
        documentEmbedMs: ms(med),
        embedSamplesMs: samples.map(ms),
        embedDocsPerSec: perSec,
      });
      log(`  batch=${String(b).padStart(2)}  向量化 ${String(ms(med)).padStart(9)} ms  ${String(perSec).padStart(6)} 块/秒   样本 [${samples.map(ms).join(', ')}]`);
    }
    report.batchSweep = sweep;
  }

  const outFile = path.join(PATHS.data, 'bench.json');
  fs.mkdirSync(PATHS.data, { recursive: true });
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2));
  log(`\n  完整 JSON 已写入 ${outFile}`);

  if (JSON_ONLY) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log('\n--- JSON ---\n');
    console.log(JSON.stringify(report, null, 2));
  }
  process.exit(0);
}

main().catch((err) => {
  console.error(err?.stack || err);
  process.exit(1);
});