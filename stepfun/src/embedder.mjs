/**
 * Node 端嵌入器（与浏览器端使用同一套 transformers.js / 同一模型 / 同一精度）。
 *
 * 用途：
 *  - scripts/verify.mjs 的无浏览器兜底路径；
 *  - scripts/bench.mjs 的分阶段计时与量化质量对比（fp32 / fp16 / q8）。
 *
 * 浏览器端（public/embedder.js）是本项目的主推理路径，语义保持一致：
 *  同模型 id、同 dtype、同 pooling、同 normalize。
 */
import { prepareNativeDeps } from './native-deps.mjs';
import { findModel, PATHS } from './config.mjs';

let transformersPromise = null;

async function loadTransformers() {
  if (!transformersPromise) {
    prepareNativeDeps({ verbose: process.env.STEPFUN_VERBOSE === '1' });
    transformersPromise = import('@huggingface/transformers');
  }
  return transformersPromise;
}

/**
 * @param {object} opts
 * @param {string} opts.modelId
 * @param {'q8'|'fp16'|'fp32'} opts.dtype
 * @param {number} [opts.batchSize]
 */
export async function createEmbedder(opts) {
  const model = findModel(opts.modelId);
  const dtype = opts.dtype || model.defaultDtype;
  const batchSize = opts.batchSize || 16;
  const { pipeline, env } = await loadTransformers();

  env.cacheDir = PATHS.modelCache;
  env.allowLocalModels = true;
  env.allowRemoteModels = true;

  const t0 = performance.now();
  const extractor = await pipeline('feature-extraction', model.id, {
    dtype,
    device: opts.device || 'cpu',
  });
  const loadMs = performance.now() - t0;

  const embedder = {
    model,
    dtype,
    batchSize,
    loadMs,
    backend: opts.device || 'cpu',

    /** 单次调用返回 [[...], ...] */
    async embed(texts, options = {}) {
      const bs = options.batchSize || batchSize;
      const out = [];
      const t = performance.now();
      for (let i = 0; i < texts.length; i += bs) {
        const batch = texts.slice(i, i + bs);
        const res = await extractor(batch, {
          pooling: model.pooling,
          normalize: model.normalize,
        });
        const data = res.data;
        const dim = res.dims[res.dims.length - 1];
        for (let j = 0; j < batch.length; j++) {
          out.push(Array.from(data.slice(j * dim, (j + 1) * dim)));
        }
      }
      const elapsedMs = performance.now() - t;
      return {
        vectors: out,
        elapsedMs,
        docsPerSec: texts.length / (elapsedMs / 1000),
        batches: Math.ceil(texts.length / bs),
      };
    },
  };
  return embedder;
}

export default createEmbedder;
