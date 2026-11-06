/**
 * 把 embedding 模型的 ONNX 权重下载到本地 .model-cache/，
 * 供浏览器通过 /models 镜像加载（离线可用 + 省掉 CDN 往返）。
 *
 * ★ 版本固定：下载地址用 src/config.mjs 里**固定到 commit SHA 的 revision**，
 *   不是会漂移的 main；下载后逐文件计算 sha256 写入 data/model-manifest.json，
 *   scripts/model-info.mjs 会离线核对本地缓存与该清单。
 *
 * 用法：npm run fetch-models [-- --model Xenova/bge-small-zh-v1.5]
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { PATHS, MODELS } from '../src/config.mjs';

const HF = 'https://huggingface.co';
const BASE_FILES = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'special_tokens_map.json',
  'vocab.txt',
  'sentence_bert_config.json',
];
const ONNX_FILES = [
  'onnx/model.onnx',          // fp32 基线
  'onnx/model_fp16.onnx',     // fp16
  'onnx/model_quantized.onnx',// int8 (动态量化)
];

const args = process.argv.slice(2);
const only = args.includes('--model') ? args[args.indexOf('--model') + 1] : null;

async function head(url) {
  const res = await fetch(url, { method: 'HEAD', redirect: 'follow' });
  if (!res.ok) return null;
  const len = res.headers.get('content-length');
  return len ? Number(len) : null;
}

function sha256(file) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(file));
  return hash.digest('hex');
}

async function download(repo, rel, revision) {
  const dest = path.join(PATHS.modelCache, repo, rel);
  if (fs.existsSync(dest)) {
    return { file: rel, size: fs.statSync(dest).size, sha256: sha256(dest), cached: true };
  }
  const url = `${HF}/${repo}/resolve/${revision}/${rel}`;
  const size = await head(url);
  if (size === null) return null; // 该文件不存在（可选文件）
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const res = await fetch(url, { redirect: 'follow' });
  if (!res.ok) throw new Error(`下载失败 ${url}: ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(dest, buf);
  return { file: rel, size: buf.length, sha256: crypto.createHash('sha256').update(buf).digest('hex'), cached: false };
}

async function main() {
  fs.mkdirSync(PATHS.modelCache, { recursive: true });
  const manifest = {};
  const pinned = {};
  for (const m of MODELS) {
    if (only && m.id !== only) continue;
    const revision = m.revisionPinned ? m.revision : 'main';
    console.log(`\n[models] ${m.id}  revision=${revision}${m.revisionPinned ? ' (pinned)' : ''}`);
    const files = {};
    for (const rel of [...BASE_FILES, ...ONNX_FILES]) {
      const r = await download(m.id, rel, revision);
      if (!r) continue;
      files[rel] = r.size;
      pinned[m.id] = pinned[m.id] || { revision, revisionPinned: !!m.revisionPinned, files: {} };
      pinned[m.id].files[rel] = { bytes: r.size, sha256: r.sha256 };
      console.log(`  ${r.cached ? 'cached' : 'downloaded'}  ${rel.padEnd(28)} ${(r.size / 1024 / 1024).toFixed(2)} MiB  ${r.sha256.slice(0, 16)}`);
    }
    manifest[m.id] = files;
  }
  const outFile = path.join(PATHS.data, 'model-files.json');
  fs.mkdirSync(PATHS.data, { recursive: true });
  const prev = fs.existsSync(outFile) ? JSON.parse(fs.readFileSync(outFile, 'utf8')) : {};
  fs.writeFileSync(outFile, JSON.stringify({ ...prev, ...manifest }, null, 2));
  console.log(`\n[models] 清单已写入 ${outFile}`);

  const pinFile = path.join(PATHS.data, 'model-manifest.json');
  const prevPin = fs.existsSync(pinFile) ? JSON.parse(fs.readFileSync(pinFile, 'utf8')) : {};
  fs.writeFileSync(pinFile, JSON.stringify({ ...prevPin, ...pinned }, null, 2));
  console.log(`[models] 版本清单（revision + 逐文件 sha256）已写入 ${pinFile}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
