/**
 * 模型体积 / 压缩比 / 维度 / 许可证 报告。
 *
 * 统计口径（对应赛题 3.2「按同一口径统计实际模型文件的总体积」）：
 *   - 权重体积 onnxBytes：该精度下真正参与推理的那一个 ONNX 文件大小；
 *   - 模型总体积 modelTotalBytes：同一精度下推理必需的
 *       config.json + tokenizer*.json + special_tokens_map.json + 权重文件 之和。
 *     各精度使用完全相同的 tokenizer/配置集合，因此两个精度可直接相除得到压缩比；
 *   - 压缩比 = FP32 总体积 / 该精度总体积（>1 表示变小）。
 * 数据来源是本机真实文件系统（.model-cache/），不是硬编码常量。
 *
 * 用法：
 *   npm run models:info             人类可读报告
 *   npm run models:info -- --json   机器可读 JSON
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { MODELS, PATHS } from '../src/config.mjs';

/** 每个精度实际加载的 ONNX 权重文件（transformers.js 的 DEFAULT_DTYPE_SUFFIX_MAPPING） */
const DTYPE_FILES = {
  fp32: 'onnx/model.onnx',
  fp16: 'onnx/model_fp16.onnx',
  q8: 'onnx/model_quantized.onnx',
};
const DTYPE_LABEL = {
  fp32: 'FP32  (基线)',
  fp16: 'FP16',
  q8: 'INT8  (动态量化)',
};

/** 与精度无关的 tokenizer / 配置文件，计入「模型总体积」 */
const AUX_FILES = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'special_tokens_map.json',
  'vocab.txt',
  'sentence_bert_config.json',
];

export function fmtBytes(n) {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(2)} KiB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(2)} MiB`;
  return `${(n / 1024 ** 3).toFixed(2)} GiB`;
}

/** 扫描 .model-cache/<modelId>/ 下的全部文件 */
function listFiles(dir) {
  const out = new Map();
  if (!fs.existsSync(dir)) return out;
  const walk = (base, rel = '') => {
    for (const e of fs.readdirSync(base, { withFileTypes: true })) {
      const full = path.join(base, e.name);
      const relPath = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) walk(full, relPath);
      else out.set(relPath, fs.statSync(full).size);
    }
  };
  walk(dir);
  return out;
}

export function collectModelInfo(model) {
  const dir = path.join(PATHS.modelCache, model.id);
  const files = listFiles(dir);
  const auxBytes = AUX_FILES.reduce((s, f) => s + (files.get(f) || 0), 0);

  const dtypes = {};
  for (const [dt, rel] of Object.entries(DTYPE_FILES)) {
    const onnxBytes = files.get(rel) ?? null;
    dtypes[dt] = {
      dtype: dt,
      label: DTYPE_LABEL[dt],
      file: rel,
      present: onnxBytes !== null,
      onnxBytes,
      auxBytes,
      modelTotalBytes: onnxBytes === null ? null : onnxBytes + auxBytes,
    };
  }
  const base = dtypes.fp32.modelTotalBytes;
  for (const dt of Object.keys(dtypes)) {
    const d = dtypes[dt];
    d.compressionRatio = (d.modelTotalBytes && base) ? base / d.modelTotalBytes : null;
    d.weightCompressionRatio = (d.onnxBytes && dtypes.fp32.onnxBytes)
      ? dtypes.fp32.onnxBytes / d.onnxBytes : null;
  }

  return {
    id: model.id,
    label: model.label,
    short: model.short,
    dim: model.dim,
    pooling: model.pooling,
    normalize: model.normalize,
    license: model.license,
    repo: `https://huggingface.co/${model.id}`,
    revision: model.revision || 'main',
    revisionPinned: model.revisionPinned === true,
    note: model.note,
    cacheDir: dir,
    present: files.size > 0,
    auxBytes,
    totalCacheBytes: [...files.values()].reduce((a, b) => a + b, 0),
    files: Object.fromEntries([...files.entries()].sort()),
    dtypes,
  };
}

export function collectAll() {
  return MODELS.map(collectModelInfo);
}

function printHuman(infos) {
  const line = '─'.repeat(78);
  console.log(line);
  console.log('  模型体积 / 压缩比报告   （数据来源：本机 .model-cache 真实文件）');
  console.log(line);
  for (const info of infos) {
    console.log('');
    console.log(`■ ${info.id}`);
    console.log(`  说明      : ${info.label}`);
    console.log(`  仓库      : ${info.repo}`);
    console.log(`  revision  : ${info.revision}${info.revisionPinned ? '' : '  (未固定到 commit SHA)'}`);
    console.log(`  许可证    : ${info.license}`);
    console.log(`  向量维度  : ${info.dim}`);
    console.log(`  pooling   : ${info.pooling} / L2 normalize = ${info.normalize}`);
    console.log(`  本地缓存  : ${info.cacheDir}`);
    if (!info.present) {
      console.log('  ⚠ 本地缓存不存在，请先运行：npm run fetch-models');
      continue;
    }
    console.log(`  tokenizer+配置 (与精度无关): ${fmtBytes(info.auxBytes)}`);
    console.log('');
    console.log('   精度            权重文件                      权重体积     模型总体积     压缩比');
    for (const dt of ['fp32', 'fp16', 'q8']) {
      const d = info.dtypes[dt];
      const ratio = d.compressionRatio ? `${d.compressionRatio.toFixed(3)}×` : '—';
      const ratioMark = dt === 'fp32' ? '  (基线)' : '';
      console.log(
        `   ${d.label.padEnd(14)} ${String(d.file).padEnd(30)} `
        + `${fmtBytes(d.onnxBytes).padStart(9)}  ${fmtBytes(d.modelTotalBytes).padStart(12)}  `
        + `${ratio.padStart(8)}${ratioMark}`,
      );
    }
    const q8 = info.dtypes.q8;
    const fp16 = info.dtypes.fp16;
    console.log('');
    console.log(`   仅权重压缩比（不含 tokenizer）: FP16 ${fp16.weightCompressionRatio ? fp16.weightCompressionRatio.toFixed(3) + '×' : '—'}`
      + `, INT8 ${q8.weightCompressionRatio ? q8.weightCompressionRatio.toFixed(3) + '×' : '—'}`);
    console.log(`   缓存目录内全部文件合计: ${fmtBytes(info.totalCacheBytes)}`);
  }
  console.log('');
  console.log(line);
  console.log('  注：压缩比 = FP32 体积 / 该精度体积，口径见文件头注释；均为实测字节数。');
  console.log(line);
}

function main() {
  const asJson = process.argv.includes('--json');
  const infos = collectAll();
  if (asJson) {
    console.log(JSON.stringify(infos, null, 2));
  } else {
    printHuman(infos);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}