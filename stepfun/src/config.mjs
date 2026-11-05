/**
 * 全局配置：模型注册表、seekdb 连接参数、服务端口。
 * 所有路径都相对项目根目录（stepfun/），保证「一条命令跑起来」。
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export const PATHS = {
  root: ROOT,
  public: path.join(ROOT, 'public'),
  modelCache: process.env.STEPFUN_MODEL_CACHE || path.join(ROOT, '.model-cache'),
  docs: path.join(ROOT, 'docs'),
  data: path.join(ROOT, 'data'),
  nodeModules: path.join(ROOT, 'node_modules'),
};

export const SERVER = {
  port: Number(process.env.PORT || 5173),
  host: process.env.HOST || '127.0.0.1',
};

export const SEEKDB = {
  host: process.env.SEEKDB_HOST || '127.0.0.1',
  port: Number(process.env.SEEKDB_PORT || 2883),
  user: process.env.SEEKDB_USER || 'root',
  password: process.env.SEEKDB_PASSWORD || '',
  tenant: process.env.SEEKDB_TENANT || 'sys',
  database: process.env.SEEKDB_DATABASE || 'stepfun',
  // 本地 seekdb server 可执行文件（用于一条命令启动）
  exe: process.env.SEEKDB_EXE ||
    'C:/codex-work/ob-00001/tools/seekdb/PFiles64/seekdb/bin/seekdb.exe',
  baseDir: process.env.SEEKDB_BASE_DIR ||
    'C:/codex-work/ob-00001/work/seekdb-stepfun',
};

/**
 * 模型注册表。
 * - source: Hugging Face 公开仓库
 * - revision: 权重来源的 revision。本机缓存由 scripts/fetch-models.mjs 从 HF resolve/main 下载，
 *   revisionPinned=false 表示未固定到具体 commit SHA（见 README「局限」）
 * - dim: 向量维度
 * - dtypes: 支持的精度，q8 = INT8 动态量化，fp16 = FP16，fp32 = 基线
 */
export const MODELS = [
  {
    id: 'Xenova/bge-small-zh-v1.5',
    label: 'BGE-small-zh-v1.5（中文，512 维）',
    short: 'bge-small-zh-v1.5',
    dim: 512,
    pooling: 'cls',
    normalize: true,
    dtypes: ['q8', 'fp16', 'fp32'],
    defaultDtype: 'q8',
    license: 'MIT',
    repo: 'https://huggingface.co/Xenova/bge-small-zh-v1.5',
    revision: 'main',
    revisionPinned: false,
    note: 'BAAI bge-small-zh-v1.5，ONNX 权重由 Xenova 转换并发布到 HF。',
  },
  {
    id: 'Xenova/all-MiniLM-L6-v2',
    label: 'all-MiniLM-L6-v2（英文，384 维）',
    short: 'all-MiniLM-L6-v2',
    dim: 384,
    pooling: 'mean',
    normalize: true,
    dtypes: ['q8', 'fp16', 'fp32'],
    defaultDtype: 'q8',
    license: 'Apache-2.0',
    repo: 'https://huggingface.co/Xenova/all-MiniLM-L6-v2',
    revision: 'main',
    revisionPinned: false,
    note: 'sentence-transformers/all-MiniLM-L6-v2，ONNX 权重由 Xenova 转换并发布到 HF。',
  },
];

export const DEFAULT_MODEL_ID = MODELS[0].id;

/** 按模型 id 查表 */
export function findModel(id) {
  return MODELS.find((m) => m.id === id) || MODELS[0];
}

/** 集合名规则：kb_<模型短名>_<精度>，用于「集合/会话状态管理」演示 */
export function collectionNameFor(modelId, dtype) {
  const m = findModel(modelId);
  return `kb_${m.short.replace(/[^a-zA-Z0-9]+/g, '_')}_${dtype}`;
}

/** 文本切分：按段落切，再按长度上限切（保留重叠），供增量导入使用 */
export const CHUNK = {
  maxChars: 480,
  overlap: 60,
  minChars: 24,
};
