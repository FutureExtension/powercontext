"""Run the verification sample end to end and record the log.

The script performs the steps of the sample: retrieve the context, run the
target feature test before the change, apply the change, run the target test
and the regression suite again, and store the results in PowerContext.

The change itself is the patch that the development assistant produced.  The
script never modifies the working tree: it copies the project into a scratch
directory, reconstructs the pre-change state there with ``git apply
--reverse`` and the post-change state with ``git apply``, and runs pytest in
each of them.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdd.config import Settings
from sdd.context import build_context
from sdd.state import TaskRecord, TaskStateStore

TASK = "为订单筛选增加按国家过滤的能力"
SCOPE = "sdd-task"
PATCH = Path(__file__).resolve().parents[1] / "evidence" / "code-change.patch"
# The scratch copy lives outside the Git repository on purpose: inside a
# repository ``git apply`` resolves the paths of a patch relative to the
# repository root, so the patch would be applied to a different tree.
WORKSPACE = Path(tempfile.gettempdir()) / "sdd-verification-workspace"


def _run_tests(project: Path, *selection: str) -> tuple[int, str]:
    """Run pytest inside the project and return the exit code and the log."""

    result = subprocess.run(
        [sys.executable, "-m", "pytest", *selection, "-q"],
        cwd=project,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _apply(workspace: Path, reverse: bool) -> bool:
    """Apply the patch in the given direction and report whether it worked."""

    command = ["git", "apply"]
    if reverse:
        command.append("--reverse")
    check = subprocess.run(
        [*command, "--check", str(PATCH)],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        return False
    return subprocess.run(
        [*command, str(PATCH)],
        cwd=workspace,
        capture_output=True,
        text=True,
    ).returncode == 0


async def main() -> int:
    settings = Settings.from_env()
    project = Path(settings.sample_project)

    bundle = await build_context(settings, TASK, SCOPE)
    print("=== 1. 检索到的上下文 ===")
    print(bundle.to_markdown())

    if not PATCH.exists():
        print(f"[失败] 找不到补丁 {PATCH}")
        return 1

    shutil.rmtree(WORKSPACE, ignore_errors=True)
    shutil.copytree(project, WORKSPACE)

    # Reconstruct the pre-change state.  The working tree may already carry
    # the change, so both directions are tried.
    if not _apply(WORKSPACE, reverse=True):
        if not _apply(WORKSPACE, reverse=False):
            print("[失败] 补丁无法在副本中应用")
            return 1

    before_code, before_log = _run_tests(
        WORKSPACE, "tests/test_filters.py", "-k", "filter_by_country"
    )
    print("\n=== 2. 修改前的目标功能测试 ===")
    print(before_log.strip()[-1200:])
    print(f"exit={before_code}")

    all_before_code, all_before_log = _run_tests(WORKSPACE, "tests")
    print("\n=== 3. 修改前的全量测试 ===")
    print(all_before_log.strip()[-800:])
    print(f"exit={all_before_code}")

    applied = _apply(WORKSPACE, reverse=False)
    after_code = None
    after_log = ""
    suite_after_code = None
    suite_after_log = ""
    if applied:
        after_code, after_log = _run_tests(
            WORKSPACE, "tests/test_filters.py", "-k", "filter_by_country"
        )
        suite_after_code, suite_after_log = _run_tests(WORKSPACE, "tests")
        print("\n=== 4. 应用补丁后的目标功能测试 ===")
        print(after_log.strip()[-1200:])
        print(f"exit={after_code}")
        print("\n=== 5. 应用补丁后的全量测试 ===")
        print(suite_after_log.strip()[-800:])
        print(f"exit={suite_after_code}")
    else:
        print("\n[失败] 补丁无法正向应用")

    shutil.rmtree(WORKSPACE, ignore_errors=True)

    state = bundle.state or TaskRecord(task=TASK, scope=SCOPE)
    state.task = TASK
    state.specs = [hit.identifier for hit in bundle.specs]
    state.symbols = [f"{hit.file_path}:{hit.title}" for hit in bundle.symbols]
    state.tests = [f"{hit.file_path}:{hit.title}" for hit in bundle.tests]
    state.done = [
        "已通过 seekdb 全文检索定位规格、代码符号与测试",
        "已在副本中重建修改前状态并运行目标功能测试",
    ]
    state.verification = [
        f"修改前目标功能测试 exit={before_code}（期望非 0）",
        f"修改前全量测试 exit={all_before_code}",
    ]
    if applied:
        state.done.append("已应用 MiniMax 产出的补丁")
        state.done.append("已运行修改后的目标功能测试与全量回归测试")
        state.verification.append(f"修改后目标功能测试 exit={after_code}（期望 0）")
        state.verification.append(f"修改后全量测试 exit={suite_after_code}（期望 0）")
    await TaskStateStore(settings).save(state)

    report = {
        "query": bundle.query,
        "code_query": bundle.code_query,
        "specs": [hit.identifier for hit in bundle.specs],
        "symbols": [f"{hit.file_path}:{hit.title}" for hit in bundle.symbols],
        "tests": [f"{hit.file_path}:{hit.title}" for hit in bundle.tests],
        "statements": bundle.statements,
        "target_test_before": {"exit": before_code},
        "suite_before": {"exit": all_before_code},
        "target_test_after": {"exit": after_code},
        "suite_after": {"exit": suite_after_code},
    }
    out = Path(settings.sample_project).parent / "verification-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {out}")

    # Before the change the target feature test has to fail, and after the
    # change both the target test and the whole suite have to pass.  The suite
    # before the change fails for the same reason, so it is expected to be
    # non-zero as well.
    ok = (
        before_code != 0
        and all_before_code != 0
        and applied
        and after_code == 0
        and suite_after_code == 0
    )
    print(f"\n验证结论：{'通过' if ok else '未通过'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))