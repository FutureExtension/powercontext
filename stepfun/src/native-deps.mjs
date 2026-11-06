/**
 * onnxruntime-node 原生依赖引导（仅 Node 端脚本需要，浏览器端完全不需要）。
 *
 * 本机环境特点：
 *  - onnxruntime-node 的原生模块需要 VC++ 运行库 (msvcp140/vcruntime140)；
 *  - 本机是精简版 Windows，System32 下没有这些 DLL，也缺少 UCRT 的 api-ms-win-* 转发器
 *    （它们在 C:\\Windows\\System32\\downlevel 下），而 Node 进程启动时会调用
 *    SetDefaultDllDirectories，导致 DLL 依赖无法从 PATH / 模块目录解析。
 *
 * 解决方式（幂等、可重复执行）：
 *  1. 把需要的 VC 运行库与 api-ms-win-* 转发器复制到 onnxruntime-node 的 bin 目录；
 *  2. 把该 bin 目录加入 process.env.PATH。
 *
 * 在已安装 Visual C++ Redistributable 的普通机器上，以上两步都会被跳过。
 */
import fs from 'node:fs';
import path from 'node:path';
import { PATHS } from './config.mjs';

const ORT_BIN = path.join(
  PATHS.nodeModules, 'onnxruntime-node', 'bin', 'napi-v6', 'win32', 'x64',
);

const NEEDED_DLLS = [
  'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
  'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll',
  'vcruntime140.dll', 'vcruntime140_1.dll',
];

function candidateDirs() {
  const dirs = [];
  const win = process.env.SystemRoot || 'C:\\Windows';
  dirs.push(path.join(win, 'System32'));
  dirs.push(path.join(win, 'System32', 'downlevel'));
  // 本机 seekdb 发行包自带 VC 运行库，可作为兜底来源
  dirs.push('C:/codex-work/ob-00001/tools/seekdb/PFiles64/seekdb/bin');
  return dirs.filter((d) => fs.existsSync(d));
}

export function prepareNativeDeps({ verbose = false } = {}) {
  const report = { ortBin: ORT_BIN, copied: [], searched: [], ok: false };
  if (process.platform !== 'win32') {
    report.ok = true;
    return report;
  }
  if (!fs.existsSync(ORT_BIN)) {
    report.ok = true; // 未安装 onnxruntime-node，交给上层报错
    return report;
  }

  // 1) 复制 VC 运行库
  const dirs = candidateDirs();
  report.searched = dirs;
  for (const dll of NEEDED_DLLS) {
    const target = path.join(ORT_BIN, dll);
    if (fs.existsSync(target)) continue;
    for (const dir of dirs) {
      const src = path.join(dir, dll);
      if (fs.existsSync(src)) {
        try {
          fs.copyFileSync(src, target);
          report.copied.push(dll);
        } catch { /* 忽略：可能没有写权限 */ }
        break;
      }
    }
  }

  // 2) 复制 UCRT 转发器（api-ms-win-*.dll）
  const downlevel = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'downlevel');
  if (fs.existsSync(downlevel)) {
    for (const file of fs.readdirSync(downlevel)) {
      if (!/^api-ms-win-.*\.dll$/i.test(file)) continue;
      const target = path.join(ORT_BIN, file);
      if (fs.existsSync(target)) continue;
      try {
        fs.copyFileSync(path.join(downlevel, file), target);
        report.copied.push(file);
      } catch { /* ignore */ }
    }
  }

  // 3) 加入 PATH（Node 的 DLL 搜索会走 PATH）
  const current = process.env.PATH || '';
  if (!current.split(';').some((p) => p.toLowerCase() === ORT_BIN.toLowerCase())) {
    process.env.PATH = `${ORT_BIN};${current}`;
  }
  report.ok = true;
  if (verbose) {
    console.log(`[native-deps] ORT bin: ${ORT_BIN}`);
    console.log(`[native-deps] copied ${report.copied.length} dll(s): ${report.copied.slice(0, 8).join(', ')}${report.copied.length > 8 ? ' …' : ''}`);
  }
  return report;
}

export default prepareNativeDeps;
