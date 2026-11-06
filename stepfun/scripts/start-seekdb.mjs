/**
 * 独立启动本地 seekdb server（MySQL 协议）。
 * 用法：npm run seekdb
 */
import fs from 'node:fs';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { SEEKDB } from '../src/config.mjs';

function reachable(port = SEEKDB.port, host = SEEKDB.host) {
  return new Promise((resolve) => {
    const s = new net.Socket();
    const done = (ok) => { s.destroy(); resolve(ok); };
    s.setTimeout(1500);
    s.once('connect', () => done(true));
    s.once('timeout', () => done(false));
    s.once('error', () => done(false));
    s.connect(port, host);
  });
}

async function main() {
  if (await reachable()) {
    console.log(`[seekdb] ${SEEKDB.host}:${SEEKDB.port} 已经在运行。`);
    return;
  }
  if (!fs.existsSync(SEEKDB.exe)) {
    console.error(`[seekdb] 找不到 seekdb 可执行文件：${SEEKDB.exe}`);
    process.exit(1);
  }
  fs.mkdirSync(SEEKDB.baseDir, { recursive: true });
  console.log(`[seekdb] 启动：${SEEKDB.exe} --base-dir ${SEEKDB.baseDir} --port ${SEEKDB.port}`);
  const child = spawn(SEEKDB.exe,
    ['--base-dir', SEEKDB.baseDir, '--nodaemon', '--port', String(SEEKDB.port)],
    { stdio: 'ignore', detached: false, windowsHide: true });
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (await reachable()) {
      console.log(`[seekdb] 就绪：${SEEKDB.host}:${SEEKDB.port}`);
      return;
    }
  }
  console.error('[seekdb] 启动超时');
  child.kill();
  process.exit(1);
}

main().catch((e) => { console.error(e); process.exit(1); });
