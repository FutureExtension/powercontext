import { createEmbedder } from '../src/embedder.mjs';
import { SeekdbService, tableNameOf } from '../src/seekdb-service.mjs';
import { findModel, collectionNameFor } from '../src/config.mjs';
import { DEMO_DOCS, chunkDocuments } from '../src/corpus.mjs';

const model = findModel('Xenova/bge-small-zh-v1.5');
console.log('model', model.id, 'dim', model.dim);
const emb = await createEmbedder({ modelId: model.id, dtype: 'q8', batchSize: 16 });
console.log('loaded in', emb.loadMs.toFixed(0), 'ms');

const chunks = chunkDocuments(DEMO_DOCS.slice(0, 6));
console.log('chunks', chunks.length);
const { vectors, elapsedMs, docsPerSec } = await emb.embed(chunks.map(c => c.text));
console.log('embed', chunks.length, 'chunks in', elapsedMs.toFixed(0), 'ms =', docsPerSec.toFixed(1), 'docs/s; dim', vectors[0].length);

const svc = new SeekdbService();
await svc.connect();
const collName = collectionNameFor(model.id, 'q8');
console.log('collection', collName);
const coll = await svc.resetCollection(collName, model);
console.log('table', tableNameOf(coll));
const docs = chunks.map((c, i) => ({ id: c.id, text: c.text, vector: vectors[i], metadata: c.metadata }));
await svc.upsertDocuments(collName, docs, model);
console.log('upserted', docs.length);
await svc.refreshIndex(collName);
console.log('count', await svc.count(collName));

const q = 'RRF 融合算法是怎么工作的';
const qv = (await emb.embed([q])).vectors[0];
const res = await svc.hybridSearch(collName, { queryText: q, queryVector: qv, topK: 5 });
console.log('--- hits ---');
for (const h of res.hits) console.log(h.rank, h.id, h.score, (h.document || '').slice(0, 40));
console.log('--- sqls ---');
for (const s of res.sqls) console.log(s.sql.slice(0, 400));
await svc.close();
