/**
 * seekdb 数据访问层。
 *
 * 关键设计（对应赛题 2.3）：
 *  - 所有向量 / 原文 / 元数据都存放在 seekdb 表中（VECTOR + STRING + JSON 列）；
 *  - 混合检索完全交给 seekdb：调用 SDK 的 `collection.hybridSearch()`，
 *    该方法在数据库侧用 `DBMS_HYBRID_SEARCH.GET_SQL` 生成「一条 SQL」，
 *    由 seekdb 自己完成「全文倒排检索 + 向量近邻检索 + RRF 融合」。
 *    客户端绝不分别取两路结果再自行拼合。
 *  - 每条真实执行的 SQL 都会被记录到 sqlLog 中，便于写进技术说明核对。
 */
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from 'seekdb';
import { SEEKDB } from './config.mjs';

export const DEFAULT_HNSW = {
  distance: 'cosine',
  type: 'hnsw',
  lib: 'vsag',
  m: 16,
  ef_construction: 200,
  ef_search: 64,
};

/**
 * seekdb-js 客户端危险关键字清单（与 node_modules/seekdb 的 validateDynamicSql 保持一致）。
 * 这些字面量出现在查询文本里会让 SDK 拒绝执行 DBMS_HYBRID_SEARCH 生成的 SQL。
 */
export const DANGEROUS_SQL_KEYWORDS = [
  'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
  'TRUNCATE', 'REPLACE', 'RENAME', 'LOAD_FILE', 'OUTFILE', 'DUMPFILE',
  'INTO OUTFILE', 'INTO DUMPFILE', 'CALL', 'LOAD',
];

/**
 * 把查询文本里的数据库保留字剔除，只影响「全文通道」的匹配词。
 * 返回 { text, removed }；removed 为被剔除的关键字列表。
 */
export function sanitizeFulltextQuery(text) {
  const src = String(text ?? '');
  let out = src;
  const removed = [];
  for (const kw of DANGEROUS_SQL_KEYWORDS) {
    const re = new RegExp(`\\b${kw.replace(/ /g, '\\s+')}\\b`, 'gi');
    if (re.test(out)) {
      removed.push(kw);
      out = out.replace(re, ' ');
    }
  }
  return { text: out.replace(/\s+/g, ' ').trim(), removed };
}
export class SeekdbService {
  constructor(options = {}) {
    this.options = {
      host: SEEKDB.host,
      port: SEEKDB.port,
      user: SEEKDB.user,
      password: SEEKDB.password,
      tenant: SEEKDB.tenant,
      database: SEEKDB.database,
      ...options,
    };
    this.client = null;
    this.collections = new Map();   // name -> Collection
    this.sqlLog = [];
    this._logSql = false;
  }

  /* ------------------------------------------------------------------ */
  /* 连接                                                                */
  /* ------------------------------------------------------------------ */
  async connect() {
    if (this.client) return this.client;
    const { host, port, user, password, tenant, database } = this.options;
    this.client = new SeekdbClient({ host, port, user, password, tenant, database });
    // 拦截内部客户端的 execute，记录真实执行的 SQL
    const internal = this.client._delegate?._internal;
    if (internal) {
      const original = internal.execute.bind(internal);
      internal.execute = async (sql, params) => {
        if (this._logSql) {
          this.sqlLog.push({ sql: String(sql), params: params ?? null, at: new Date().toISOString() });
        }
        return original(sql, params);
      };
    }
    await this.ensureDatabase();
    return this.client;
  }

  async ensureDatabase() {
    const admin = new (await import('seekdb')).AdminClient({
      host: this.options.host,
      port: this.options.port,
      user: this.options.user,
      password: this.options.password,
      tenant: this.options.tenant,
    });
    try {
      await admin.createDatabase(this.options.database, this.options.tenant);
    } catch (err) {
      // 已存在时忽略
      if (!/exist|already/i.test(String(err?.message))) throw err;
    } finally {
      await admin.close().catch(() => {});
    }
  }

  async close() {
    if (this.client) {
      await this.client.close().catch(() => {});
      this.client = null;
      this.collections.clear();
    }
  }

  /* ------------------------------------------------------------------ */
  /* 集合管理                                                            */
  /* ------------------------------------------------------------------ */
  /**
   * 创建（或复用）集合。
   * 表结构：id VARBINARY(512) / document STRING / embedding VECTOR(dim) /
   *         metadata JSON + FULLTEXT INDEX(idx_fts, ik) + VECTOR INDEX(idx_vec, hnsw/vsag)
   */
  async ensureCollection(name, model, opts = {}) {
    await this.connect();
    const cached = this.collections.get(name);
    if (cached) return cached;

    const exists = await this.client.hasCollection(name);
    if (!exists) return this._createCollection(name, model, opts);

    // embeddingFunction: null —— 明确告诉 SDK「向量由客户端（浏览器）算好后直接写入」。
    // 不传这个参数时，SDK 会去解析默认嵌入函数 default-embed，而它是可选依赖
    // @seekdb/default-embed（本机未安装），直接抛
    // 「Embedding function 'default-embed' is not registered.」，导致任何写入都失败。
    const collection = await this.client.getCollection({ name, embeddingFunction: null });
    this.collections.set(name, collection);
    return collection;
  }

  /** 创建一个「向量由客户端写入」的集合：不登记任何服务端嵌入函数。 */
  async _createCollection(name, model, opts = {}) {
    const schema = new Schema({
      fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
      vectorIndex: new VectorIndexConfig({
        hnsw: { ...DEFAULT_HNSW, dimension: model.dim, ...(opts.hnsw || {}) },
        // embeddingFunction: null —— 明确声明「向量由客户端（浏览器）生成后写入」，
        // 避免 SDK 去加载可选依赖 @seekdb/default-embed 在服务端做嵌入。
        embeddingFunction: null,
      }),
    });
    const collection = await this.client.createCollection({ name, schema });
    this.collections.set(name, collection);
    return collection;
  }

  async getCollection(name) {
    await this.connect();
    if (this.collections.has(name)) return this.collections.get(name);
    const collection = await this.client.getCollection({ name });
    this.collections.set(name, collection);
    return collection;
  }

  async resetCollection(name, model, opts = {}) {
    await this.connect();
    this.collections.delete(name);
    if (await this.client.hasCollection(name)) {
      await this.client.deleteCollection(name);
    }
    return this._createCollection(name, model, opts);
  }

  async listCollections() {
    await this.connect();
    const list = await this.client.listCollections({ withEmbeddingFunction: false });
    return list.map((c) => c.name);
  }

  async count(name) {
    const collection = await this.getCollection(name);
    return collection.count();
  }

  /* ------------------------------------------------------------------ */
  /* 写入 / 刷新                                                         */
  /* ------------------------------------------------------------------ */
  /**
   * 增量写入。docs: [{ id, text, vector, metadata }]
   * 使用 upsert 保证重复导入（同一 id）不会产生重复行。
   */
  async upsertDocuments(name, docs, model) {
    const collection = await this.ensureCollection(name, model);
    if (!docs.length) return { written: 0 };
    const ids = docs.map((d) => d.id);
    const documents = docs.map((d) => d.text);
    const embeddings = docs.map((d) => d.vector);
    const metadatas = docs.map((d) => d.metadata ?? {});
    await collection.upsert({ ids, documents, embeddings, metadatas });
    return { written: docs.length };
  }

  /** 刷新索引，让新写入立即可被检索 */
  async refreshIndex(name) {
    const collection = await this.getCollection(name);
    await collection.refresh_index();
  }

  /* ------------------------------------------------------------------ */
  /* 混合检索（由 seekdb 完成）                                           */
  /* ------------------------------------------------------------------ */
  /**
   * @param {string} name        集合名
   * @param {object} p
   * @param {string} p.queryText  用户查询原文（走 seekdb 全文倒排 + BM25）
   * @param {number[]} p.queryVector 查询向量（走 seekdb HNSW 近邻）
   * @param {number} p.topK
   * @param {object} p.rrf        { rankWindowSize, rankConstant }
   */
  async hybridSearch(name, p) {
    const collection = await this.getCollection(name);
    const topK = p.topK ?? 10;
    const rrf = p.rrf ?? { rankWindowSize: 60, rankConstant: 60 };
    this._logSql = true;
    const logStart = this.sqlLog.length;
    const t0 = performance.now();
    const warnings = [];
    const runSearch = (fulltextQuery) => collection.hybridSearch({
      // 全文侧：seekdb 的全文索引（ik 分词）BM25 检索
      query: { whereDocument: { $contains: fulltextQuery } },
      // 向量侧：seekdb HNSW 近邻检索
      knn: { queryEmbeddings: p.queryVector, nResults: topK },
      // 融合：seekdb 侧 RRF
      rank: { rrf: { rankWindowSize: rrf.rankWindowSize, rankConstant: rrf.rankConstant } },
      nResults: topK,
      include: ['documents', 'metadatas', 'embeddings', 'distances'],
    });
    let result;
    try {
      try {
        result = await runSearch(p.queryText);
      } catch (err) {
        // seekdb-js 客户端会扫描 DBMS_HYBRID_SEARCH 生成的 SQL，遇到 CALL / LOAD /
        // SELECT 等危险字面量就判为注入并拒绝执行（见 node_modules/seekdb 的
        // validateDynamicSql）。这里只对「全文通道」的查询文本做安全降级：
        // 剔除这些字面量后用同一个 seekdb 混合检索重试，向量通道的查询向量保持不变，
        // 融合依旧全部发生在数据库侧，客户端不做两路结果拼合。
        if (!/Dangerous SQL keyword detected/i.test(String(err?.message || ''))) throw err;
        const { text, removed } = sanitizeFulltextQuery(p.queryText);
        warnings.push(
          `查询文本包含数据库保留字 [${removed.join(', ')}]，全文通道已剔除这些字面量后重试；`
          + '向量通道（查询向量）未受影响，融合仍在 seekdb 内完成。',
        );
        result = await runSearch(text);
      }
    } finally {
      this._logSql = false;
    }
    const elapsedMs = performance.now() - t0;

    const ids = result.ids?.[0] ?? [];
    const documents = result.documents?.[0] ?? [];
    const metadatas = result.metadatas?.[0] ?? [];
    const embeddings = result.embeddings?.[0] ?? [];
    const distances = result.distances?.[0] ?? [];

    const hits = ids.map((id, i) => ({
      id: String(id),
      rank: i + 1,
      score: typeof distances[i] === 'number' ? distances[i] : null,
      document: documents[i] ?? null,
      metadata: metadatas[i] ?? null,
      vector: embeddings[i] ?? null,
    }));

    // 取出本次混合检索真正执行的 SQL（供技术说明核对）
    const sqls = this.sqlLog.slice(logStart);
    if (this.sqlLog.length > 500) this.sqlLog.splice(0, this.sqlLog.length - 500);
    return { hits, elapsedMs, sqls, rrf, warnings };
  }

  /* ------------------------------------------------------------------ */
  /* 校验 / 排查用                                                       */
  /* ------------------------------------------------------------------ */
  async rawSql(sql, params) {
    await this.connect();
    return this.client.execute(sql, params);
  }

  async describe(name) {
    const collection = await this.getCollection(name);
    return this.rawSql(`DESC \`${tableNameOf(collection)}\``);
  }
}

/** 集合对应的物理表名（seekdb v2 集合使用 c$v2$<collectionId>） */
export function tableNameOf(collection) {
  return collection.collectionId ? `c$v2$${collection.collectionId}` : `c$v1$${collection.name}`;
}

export default SeekdbService;
