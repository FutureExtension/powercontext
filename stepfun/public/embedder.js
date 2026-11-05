/**
 * 浏览器端向量化模块。
 *
 * ★ 本文件是赛题「浏览器端向量化」的核心实现：
 *   文档向量与查询向量 **全部** 在用户设备上由 transformers.js + ONNX Runtime Web 计算，
 *   没有任何一个字节的推理请求发往云端推理 API。
 *
 * 后端选择：
 *   1. 优先 WebGPU：显式检测 navigator.gpu 并 requestAdapter()，再以 device:'webgpu' 创建会话；
 *   2. 任何环节失败 → 自动降级 WASM（device:'wasm'），并在界面上给出降级原因。
 */
import { pipeline, env } from '/vendor/transformers.web.min.js';

// ---------------------------------------------------------------------------
// 全局环境配置：模型优先从本机 /models 镜像加载（离线可用、无 CDN 往返），
// 失败时回落到 Hugging Face 官方仓库；ORT 的 wasm 运行时同样走本机。
// ---------------------------------------------------------------------------
env.allowLocalModels = true;
env.allowRemoteModels = true;
env.localModelPath = '/models/';
env.useBrowserCache = true;
env.backends.onnx.wasm.wasmPaths = {
  mjs: '/vendor/ort/ort-wasm-simd-threaded.asyncify.mjs',
  wasm: '/vendor/ort/ort-wasm-simd-threaded.asyncify.wasm',
};
env.backends.onnx.wasm.numThreads = Math.max(
  1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1),
);
env.backends.onnx.wasm.simd = true;

/** dtype -> transformers.js 的 onnx 文件后缀（与官方 DEFAULT_DTYPE_SUFFIX_MAPPING 一致） */
export const DTYPE_FILE = {
  fp32: 'model.onnx',
  fp16: 'model_fp16.onnx',
  q8: 'model_quantized.onnx',
  int8: 'model_int8.onnx',
  uint8: 'model_uint8.onnx',
};

/** ---------------------------------------------------------------------------
 *  后端探测
 *  ------------------------------------------------------------------------- */
export async function probeBackend() {
  const info = {
    backend: 'wasm',
    reason: '',
    webgpu: { available: false, adapter: null, error: null },
  };
  if (typeof navigator === 'undefined' || !navigator.gpu) {
    info.reason = '浏览器未暴露 navigator.gpu（WebGPU 不可用）';
    return info;
  }
  info.webgpu.available = true;
  try {
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
    if (!adapter) {
      info.reason = 'navigator.gpu.requestAdapter() 返回 null（没有可用的 GPU 适配器）';
      return info;
    }
    const ai = adapter.info || (adapter.requestAdapterInfo ? await adapter.requestAdapterInfo() : null);
    info.webgpu.adapter = ai
      ? { vendor: ai.vendor, architecture: ai.architecture, device: ai.device, description: ai.description }
      : { description: 'adapter.info 不可用（浏览器未暴露）' };
    info.backend = 'webgpu';
    info.reason = 'WebGPU 适配器申请成功';
  } catch (err) {
    info.webgpu.error = String(err?.message || err);
    info.reason = `WebGPU 初始化异常：${info.webgpu.error}`;
  }
  return info;
}

/** ---------------------------------------------------------------------------
 *  嵌入器
 *  ------------------------------------------------------------------------- */
export class Embedder {
  constructor() {
    this.extractor = null;
    this.model = null;
    this.dtype = null;
    this.device = null;
    this.backendInfo = null;
    this.loadMs = 0;
    this.downloadMs = 0;
    this.loadedFiles = [];
  }

  get ready() { return !!this.extractor; }

  /**
   * 加载模型（带 WebGPU → WASM 自动降级）。
   * @param {object} o
   * @param {string} o.modelId   HF 仓库 id，如 'Xenova/bge-small-zh-v1.5'
   * @param {string} o.dtype     'q8' | 'fp16' | 'fp32'
   * @param {object} o.modelMeta 配置元信息（dim/pooling/normalize）
   * @param {(p:any)=>void} [o.onProgress] 下载进度回调
   */
  async load({ modelId, dtype, modelMeta, onProgress }) {
    const t0 = performance.now();
    const probe = await probeBackend();
    this.backendInfo = probe;

    const attempts = [];
    if (probe.backend === 'webgpu') attempts.push('webgpu');
    attempts.push('wasm');

    let lastErr = null;
    for (const device of attempts) {
      try {
        const extractor = await pipeline('feature-extraction', modelId, {
          dtype,
          device,
          progress_callback: onProgress,
        });
        this.extractor = extractor;
        this.device = device;
        this.dtype = dtype;
        this.model = modelMeta;
        this.loadMs = performance.now() - t0;
        this.backendInfo = {
          ...probe,
          backend: device,
          reason: device === 'webgpu'
            ? probe.reason
            : `已降级到 WASM：${probe.reason || 'WebGPU 不可用'}`,
          fallback: device !== 'webgpu',
        };
        return this.backendInfo;
      } catch (err) {
        lastErr = err;
        this.backendInfo = {
          ...probe,
          backend: 'wasm',
          reason: `加载 ${device} 后端失败：${err?.message || err}`,
          fallback: true,
        };
        if (device === 'wasm') break;
      }
    }
    throw lastErr || new Error('模型加载失败');
  }

  /**
   * 批量向量化。全部在本地线程完成。
   * @param {string[]} texts
   * @param {object} o
   * @param {number} [o.batchSize]
   * @param {(done:number,total:number)=>void} [o.onProgress]
   */
  async embed(texts, { batchSize = 16, onProgress } = {}) {
    if (!this.extractor) throw new Error('模型尚未加载');
    const pool = this.model?.pooling || 'mean';
    const normalize = this.model?.normalize !== false;
    const out = [];
    const t0 = performance.now();
    let done = 0;
    for (let i = 0; i < texts.length; i += batchSize) {
      const batch = texts.slice(i, i + batchSize);
      const res = await this.extractor(batch, { pooling: pool, normalize });
      const dim = res.dims[res.dims.length - 1];
      const data = res.data;
      for (let j = 0; j < batch.length; j++) {
        out.push(Array.from(data.slice(j * dim, (j + 1) * dim)));
      }
      done += batch.length;
      if (onProgress) onProgress(done, texts.length);
    }
    const elapsedMs = performance.now() - t0;
    return {
      vectors: out,
      elapsedMs,
      docsPerSec: texts.length / (elapsedMs / 1000),
      batches: Math.ceil(texts.length / batchSize),
    };
  }
}

/** ---------------------------------------------------------------------------
 *  文本切分（与服务端 src/corpus.mjs 保持同一套规则）
 *  ------------------------------------------------------------------------- */
export function chunkDocuments(docs, { maxChars = 480, overlap = 60, minChars = 24 } = {}) {
  const out = [];
  for (const doc of docs) {
    const text = (doc.text || '').replace(/\r\n/g, '\n').trim();
    const paragraphs = text.split(/\n{1,}/).map((p) => p.trim()).filter(Boolean);
    let buffer = '';
    let start = 0;
    let part = 0;
    const flush = (end) => {
      const body = buffer.trim();
      if (body.length >= minChars || out.length === 0) {
        out.push({
          id: `${doc.id}#${part}`,
          text: body,
          metadata: {
            doc_id: doc.id,
            title: doc.title || '',
            lang: doc.lang || '',
            part,
            char_start: start,
            char_end: end,
          },
        });
      }
      part += 1;
    };
    for (const p of paragraphs) {
      if (buffer.length + p.length + 1 <= maxChars) {
        buffer = buffer ? `${buffer}\n${p}` : p;
      } else {
        if (buffer) {
          const end = start + buffer.length;
          flush(end);
          const keep = buffer.slice(Math.max(0, buffer.length - overlap));
          start = end - keep.length;
          buffer = keep ? `${keep}\n${p}` : p;
        } else {
          buffer = p;
        }
      }
    }
    if (buffer.trim()) flush(start + buffer.length);
  }
  return out;
}
