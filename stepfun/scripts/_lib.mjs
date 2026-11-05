/**
 * 交付脚本共用的工具函数。
 *  - ensureSeekdb()：确保本地 seekdb server 在跑（一条命令即可验证，不需要人工先起数据库）；
 *  - median / percentile：性能统计（赛题要求报中位数而不是最快一次）；
 *  - cosine()：向量余弦相似度，用于核对「写进 seekdb 的向量」与「浏览器/Node 端算出的向量」一致。
 */
import net from 'node:net';
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { SEEKDB } from '../src/config.mjs';

/** 端口是否可达 */
export function reachable(port = SEEKDB.port, host = SEEKDB.host, timeout = 1500) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    const done = (ok) => { s.destroy(); resolve(ok); };
    s.setTimeout(timeout);
    s.once('connect', () => done(true));
    s.once('timeout', () => done(false));
    s.once('error', () => done(false));
    s.connect(port, host);
  });
}

/**
 * 确保 seekdb 可用；不可用时用本机 seekdb.exe 拉起一个独立进程。
 * 返回 { started: boolean, note: string }。
 */
export async function ensureSeekdb({ quiet = false, waitSec = 120 } = {}) {
  if (await reachable()) {
    return { started: false, note: `seekdb 已在运行 (${SEEKDB.host}:${SEEKDB.port})` };
  }
  if (!fs.existsSync(SEEKDB.exe)) {
    throw new Error(`找不到 seekdb 可执行文件：${SEEKDB.exe}（请先启动本地 seekdb server）`);
  }
  fs.mkdirSync(SEEKDB.baseDir, { recursive: true });
  if (!quiet) console.log(`[seekdb] 启动 ${SEEKDB.exe} --base-dir ${SEEKDB.baseDir} --port ${SEEKDB.port}`);
  const child = spawn(SEEKDB.exe,
    ['--base-dir', SEEKDB.baseDir, '--nodaemon', '--port', String(SEEKDB.port)],
    { detached: true, stdio: 'ignore', windowsHide: true });
  child.unref();
  for (let i = 0; i < waitSec; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (await reachable()) {
      return { started: true, note: `seekdb 已启动 (${SEEKDB.host}:${SEEKDB.port})` };
    }
  }
  throw new Error('seekdb 启动超时');
}

/** 中位数 */
export function median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** 百分位（线性插值） */
export function percentile(arr, p) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const idx = (s.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return s[lo];
  return s[lo] + (s[hi] - s[lo]) * (idx - lo);
}

/** 余弦相似度 */
export function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (!na || !nb) return 0;
  return dot / Math.sqrt(na * nb);
}

/** L2 范数 */
export function norm(v) {
  let s = 0;
  for (const x of v) s += x * x;
  return Math.sqrt(s);
}

/** 轮询直到 fn 返回真值 */
export async function waitFor(fn, { timeoutMs = 60000, intervalMs = 250 } = {}) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const v = await fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`waitFor 超时（${timeoutMs} ms）`);
}

/** 极简断言器：记录通过/失败，失败不立即退出，便于一次性跑完所有阶段 */
export class Checker {
  constructor() {
    this.items = [];
    this.stage = '';
  }
  setStage(name) {
    this.stage = name;
    console.log(`\n\x1b[36m▸ ${name}\x1b[0m`);
  }
  ok(cond, label, detail = '') {
    const pass = !!cond;
    this.items.push({ stage: this.stage, label, pass, detail: String(detail) });
    const mark = pass ? '\x1b[32m✔ PASS\x1b[0m' : '\x1b[31m✔ FAIL\x1b[0m';
    console.log(`  ${mark}  ${label}${detail ? `  \x1b[90m${detail}\x1b[0m` : ''}`);
    return pass;
  }
  info(label, detail = '') {
    console.log(`  \x1b[90m· ${label}${detail ? `  ${detail}` : ''}\x1b[0m`);
  }
  get failed() {
    return this.items.filter((i) => !i.pass);
  }
  summary() {
    const total = this.items.length;
    const bad = this.failed;
    console.log(`\n${'─'.repeat(70)}`);
    console.log(`  断言总数 ${total} · 通过 ${total - bad.length} · 失败 ${bad.length}`);
    if (bad.length) {
      console.log('\n  失败明细：');
      for (const b of bad) console.log(`   ✗ [${b.stage}] ${b.label} ${b.detail}`);
    }
    console.log(`${'─'.repeat(70)}\n`);
    return bad.length === 0;
  }
}

/** 秒 → 毫秒，四舍五入到 2 位 */
export const ms = (v) => Number(v.toFixed(2));