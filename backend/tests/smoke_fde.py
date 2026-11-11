"""L05 API 级验收：CodexFDE 工作台在真实 HTTP 上的行为。

前置：后端已运行（127.0.0.1:8000）。
运行：./.venv/Scripts/python.exe -X utf8 tests/smoke_fde.py

与 tests/test_fde_ledger.py 的分工：
- 那个测**规则**（纯函数，不需要服务）；
- 这个测**行为**（真实 HTTP + 真实数据库 + 真实证据文件）。

本脚本会把本次升级的真实运行记录（红灯/绿灯日志、写集清单）登记进工作台，
所以它既是回归测试，也是工作台数据的来源。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
TMP = Path(r"E:\drill-system\tmp")
DB = ROOT / "drill.db"

SPEC_CMD = "python -X utf8 -m unittest tests.test_fde_ledger -v"
WRITE_SET_FILES = [
    "backend/app/services/fde_ledger.py",
    "backend/tests/test_fde_ledger.py",
    "backend/app/models.py",
    "backend/app/database.py",
    "backend/app/schemas.py",
    "backend/app/routers/fde.py",
    "backend/tests/smoke_fde.py",
    "frontend/src/api/fde.ts",
    "frontend/src/api/client.ts",
    "frontend/src/types/api.ts",
    "frontend/src/pages/FdeWorkbenchPage.tsx",
    "AGENTS.md",
]

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> bool:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  <- {extra}" if extra and not ok else ""))
    return ok


def call(method: str, path: str, token: str | None = None, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def login(username: str, password: str) -> str:
    status, body = call("POST", "/api/auth/login", payload={"username": username, "password": password})
    assert status == 200, f"登录失败 {username}: {status} {body}"
    return body["access_token"]


def mtime_utc(path: Path) -> str:
    """用文件真实修改时间作为观察时间——不手填，避免时区错序。"""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def midpoint_utc(earlier: Path, later: Path) -> str:
    """写集证据的观察时间取红灯与绿灯的真实中点。

    为什么不用实现文件的 mtime：绿灯之后往往还会继续改动（重构、修 typo），
    那会让「写集」的时间落在绿灯**之后**，红-改-绿顺序当场断裂。
    写集在构造上必然发生在红灯与绿灯之间，取中点是被两端真实时间夹住的估计。
    """
    a = earlier.stat().st_mtime
    b = later.stat().st_mtime
    return datetime.fromtimestamp(a + (b - a) / 2, tz=timezone.utc).isoformat()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def compute_write_set() -> str:
    lines = ["# 本次升级的写集（改动文件 + 字节数 + SHA-256）", ""]
    for rel in WRITE_SET_FILES:
        p = Path(r"E:\drill-system") / rel
        if not p.exists():
            lines.append(f"{rel}\t<缺失>")
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{p.stat().st_size} bytes\tsha256:{digest}")
    return "\n".join(lines)


def reset_fixture() -> None:
    """测试夹具：清掉 fde_* 四张表，让脚本可重复运行。

    这是**测试夹具**动作，不是工作台动作——工作台本身没有删除接口，
    因为「失败请求不得抹掉既有记录」是它的边界。
    """
    conn = sqlite3.connect(DB)
    for table in ("fde_task_events", "fde_evidences", "fde_tasks", "fde_projects"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()
    print("  [fixture] fde_* 表已清空（仅测试夹具）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-reset", action="store_true", help="保留既有 fde 数据（默认重置）")
    args = parser.parse_args()

    red_log, green_log = TMP / "l05_red.txt", TMP / "l05_green.txt"
    for f in (red_log, green_log):
        if not f.exists():
            print(f"缺少证据文件 {f}，请先运行 L05 单元测试生成。")
            return 2
    red_text, green_text = read(red_log), read(green_log)

    print("== 0. 服务与夹具 ==")
    status, body = call("GET", "/health")
    check("后端健康检查 200", status == 200, str(body))
    if not args.no_reset:
        reset_fixture()

    print("== 1. 登录（构建者 / 复核者）==")
    builder_token = login("student01", "Test@2025")
    reviewer_token = login("teacher01", "Test@2025")
    check("构建者与复核者分别取得令牌", bool(builder_token and reviewer_token))

    print("== 2. 工作台口径 ==")
    status, meta = call("GET", "/api/fde/meta", builder_token)
    check("meta 返回六段式合同", status == 200 and len(meta["spec_sections"]) == 6, str(meta)[:200])
    stage_keys = {s["key"] for s in meta["stages"]}
    check("meta 含 review / accepted 状态", {"review", "accepted", "rework"} <= stage_keys, str(sorted(stage_keys)))
    print(f"     原则：{meta.get('principle', '')}")

    print("== 3. 需求入口必须拒绝不完整的合同（L03）==")
    bad_spec = "## 目标\n做点东西\n\n## 范围\n全部\n"
    status, res = call("POST", "/api/fde/specs/validate", builder_token, {"spec_snapshot": bad_spec})
    check("缺章节的合同校验返回 ok=false", status == 200 and res["ok"] is False, str(res)[:200])
    check("问题清单点名「非目标」", any("非目标" in i for i in res["issues"]), str(res["issues"]))
    check("未填章节被算进 missing", "非目标" in res["missing"])

    print("== 4. 登记项目与任务（不合格合同不许进门）==")
    status, proj = call("POST", "/api/fde/projects", builder_token, {
        "code": "CUSTOMER-DRILL", "name": "客服演练系统",
        "purpose": "AI 扮演客户 + 多维评分的客服培训平台，本工作台为其受控交付提供台账。",
        "path": r"E:\drill-system",
    })
    if status == 409:
        status, projects = call("GET", "/api/fde/projects", builder_token)
        proj = next(p for p in projects if p["code"] == "CUSTOMER-DRILL")
    check("项目已登记", status == 201 or status == 200, str(proj)[:200])

    status, res = call("POST", "/api/fde/tasks", builder_token, {
        "project_id": proj["id"], "code": "L05-BAD", "title": "不完整合同",
        "request": "", "spec_snapshot": bad_spec,
    })
    check("不完整合同登记被拒 422", status == 422, f"{status} {str(res)[:200]}")

    full_spec = read(Path(r"E:\drill-system\tmp\l05_spec.md")) if (TMP / "l05_spec.md").exists() else None
    if not full_spec:
        full_spec = "\n\n".join(
            f"## {s}\n{s}的内容。" for s in ("目标", "范围", "非目标", "约束", "验收标准", "完成定义")
        )

    status, task_a = call("POST", "/api/fde/tasks", builder_token, {
        "project_id": proj["id"], "code": "L05-A", "title": "工作台台账核心：合同·状态机·责任分离",
        "request": "结合 CodexFDE L01–L04 机制升级客服工作台，把需求合同、状态机、证据链、责任分离补齐。",
        "spec_snapshot": full_spec,
    })
    check("完整合同登记成功 201", status == 201, f"{status} {str(task_a)[:200]}")
    check("新任务进入 spec_ready（需求已冻结）", task_a.get("state") == "spec_ready", str(task_a.get("state")))

    status, task_b = call("POST", "/api/fde/tasks", builder_token, {
        "project_id": proj["id"], "code": "L05-B", "title": "依赖 A 的后续任务",
        "request": "演示前置任务资格门禁。", "spec_snapshot": full_spec, "depends_on": ["L05-A"],
    })
    check("依赖任务登记成功 201", status == 201, f"{status} {str(task_b)[:200]}")

    status, res = call("POST", "/api/fde/tasks", builder_token, {
        "project_id": proj["id"], "code": "L05-ORPHAN", "title": "依赖不存在的前置",
        "request": "", "spec_snapshot": full_spec, "depends_on": ["NOT-EXIST"],
    })
    check("依赖不存在的前置任务被拒 422", status == 422, f"{status}")

    print("== 5. 前置未接受 → 门禁拒绝（L04）==")
    status, gate_b = call("GET", f"/api/fde/tasks/{task_b['id']}/gate", builder_token)
    check("B 的门禁未通过", status == 200 and gate_b["allowed"] is False, str(gate_b)[:200])
    check("B 被前置任务未接受挡住", any("L05-A" in r for r in gate_b["blockers"]), str(gate_b["blockers"]))

    print("== 6. 登记真实证据：红灯 → 写集 → 绿灯 ==")
    evidences = [
        ("red", SPEC_CMD, red_text, 1, mtime_utc(red_log)),
        ("diff", "# 写集清单（不是命令，是本次改动的事实）", compute_write_set(), 0,
         midpoint_utc(red_log, green_log)),
        ("green", SPEC_CMD, green_text, 0, mtime_utc(green_log)),
    ]
    for phase, command, output, code, observed in evidences:
        status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/evidences", builder_token, {
            "phase": phase, "command_text": command, "output": output,
            "return_code": code, "observed_at": observed,
        })
        check(f"{phase} 证据已登记 201", status == 201, f"{status} {str(res)[:160]}")

    status, detail_a = call("GET", f"/api/fde/tasks/{task_a['id']}", builder_token)
    check("证据链判定为完整（同一命令、红→改→绿有序）",
          detail_a["evidence_complete"] is True, str(detail_a["issues"]))
    check("红灯确实是失败记录（返回码非 0）",
          any(e["phase"] == "red" and e["return_code"] != 0 for e in detail_a["evidences"]))
    check("此时 acceptance 仍是 pending_human_review",
          detail_a["acceptance"] == "pending_human_review", detail_a["acceptance"])

    print("== 7. 状态机：不许跳阶段 ==")
    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/transition", builder_token,
                       {"target": "review", "note": "试图从 spec_ready 直接跳到 review"})
    check("跳阶段被拒 409", status == 409, f"{status} {str(res)[:160]}")

    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/transition", builder_token,
                       {"target": "executing", "note": "进入受控执行"})
    check("spec_ready → executing 允许", status == 200 and res["state"] == "executing", f"{status}")

    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/evaluate", builder_token)
    check("自动复验后进入 review", status == 200 and res["state"] == "review", f"{status} {str(res)[:160]}")

    print("== 8. 核心区分：记录齐全 ≠ 已被接受 ==")
    status, gate_a = call("GET", f"/api/fde/tasks/{task_a['id']}/gate", builder_token)
    check("证据齐全但门禁仍未通过", gate_a["allowed"] is False, str(gate_a)[:200])
    check("门禁明说卡在「未被具名接受」", any("接受" in r for r in gate_a["blockers"]), str(gate_a["blockers"]))
    check("evidence_complete 与 accepted 是两个字段",
          gate_a["evidence_complete"] is True and gate_a["accepted"] is False)

    print("== 9. 责任分离：构建者不能自签、机器不能替人签 ==")
    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/accept", builder_token, {"note": "自签尝试"})
    check("构建者自签被拒 403", status == 403, f"{status} {str(res)[:160]}")

    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/accept", reviewer_token,
                       {"actor": "agent:codex", "note": "机器代签尝试"})
    check("agent: 前缀署名被拒 403", status == 403, f"{status} {str(res)[:160]}")

    status, res = call("POST", f"/api/fde/tasks/{task_a['id']}/accept", reviewer_token,
                       {"note": "由复核者具名接受"})
    ok_accept = status == 200 and res.get("acceptance") == "accepted"
    check("复核者具名接受成功", ok_accept, f"{status} {str(res)[:200]}")
    if not ok_accept:
        print("\n接受失败，后续断言失效，提前退出。")
        return 1
    check("签收人被记录", bool(res.get("accepted_by")) and res["accepted_by"] != res["created_by"],
          f"accepted_by={res.get('accepted_by')} created_by={res.get('created_by')}")
    check("状态落到 accepted", res.get("state") == "accepted", str(res.get("state")))

    status, gate_a2 = call("GET", f"/api/fde/tasks/{task_a['id']}/gate", builder_token)
    check("接受之后门禁才放行", gate_a2["allowed"] is True and gate_a2["code"] == 0, str(gate_a2)[:200])

    print("== 10. 失败请求没有抹掉既有记录 ==")
    status, detail_a2 = call("GET", f"/api/fde/tasks/{task_a['id']}", builder_token)
    check("三次被拒之后证据仍在（3 条）", len(detail_a2["evidences"]) == 3, str(len(detail_a2["evidences"])))
    kinds = {e["kind"] for e in detail_a2["events"]}
    check("事件链含 spec/evidence/transition/evaluate/acceptance",
          {"spec", "evidence", "transition", "evaluate", "acceptance"} <= kinds, str(sorted(kinds)))
    rejected = [e for e in detail_a2["events"] if e["kind"] == "rejected"]
    check("被门禁拒绝的尝试也留在事件链里", len(rejected) >= 3, str(len(rejected)))
    check("事件只追加（7 次成功动作 + 3 次被拒 ≥ 10）", len(detail_a2["events"]) >= 10, str(len(detail_a2["events"])))

    print("== 11. 依赖门禁解除 ==")
    status, gate_b2 = call("GET", f"/api/fde/tasks/{task_b['id']}/gate", builder_token)
    check("B 不再被前置任务挡住", not any("L05-A 尚未被具名接受" in r for r in gate_b2["blockers"]),
          str(gate_b2["blockers"]))
    check("B 仍被自身条件挡住", gate_b2["allowed"] is False, str(gate_b2["blockers"]))

    print("== 12. 台账总览 ==")
    status, summary = call("GET", "/api/fde/ledger/summary", builder_token)
    check("总览返回任务数与状态分布", status == 200 and summary["tasks"] == 2, str(summary)[:200])
    check("总览记下 1 个已接受任务", summary["acceptance"].get("accepted", 0) >= 1, str(summary["acceptance"]))
    print(f"     状态分布：{json.dumps(summary['states'], ensure_ascii=False)}")

    print("== 13. L10 有界修复回路 + L15 交付摘要 ==")
    # A：全流程零返工 → 回路 ready；摘要已收敛且四要素齐全
    status, detail_a3 = call("GET", f"/api/fde/tasks/{task_a['id']}", builder_token)
    check("A 的修复回路为 ready（零返工）",
          detail_a3["repair_loop"]["status"] == "ready" and detail_a3["repair_loop"]["rounds"] == 0,
          str(detail_a3["repair_loop"])[:160])
    summary_a = detail_a3["delivery_summary"]
    check("A 的交付摘要已收敛且四要素齐全",
          summary_a["converged"] is True and set(summary_a["four"]) == {"结果", "证据", "边界", "交接"},
          str(summary_a)[:120])
    check("A 的摘要 Markdown 带绿灯命令与边界（非目标）",
          SPEC_CMD in summary_a["markdown"] and "非目标" in summary_a["markdown"], "")

    # B：驱动两轮同因返工 → stopped_no_progress
    call("POST", f"/api/fde/tasks/{task_b['id']}/transition", builder_token,
         {"target": "executing", "note": "进入执行以驱动修复回路用例"})
    status, res = call("POST", f"/api/fde/tasks/{task_b['id']}/evaluate", builder_token)
    check("B 第一轮复验退回返工", status == 200 and res["state"] == "rework", f"{status} {str(res)[:120]}")
    call("POST", f"/api/fde/tasks/{task_b['id']}/transition", builder_token,
         {"target": "executing", "note": "开修（第一轮）"})
    status, res = call("POST", f"/api/fde/tasks/{task_b['id']}/evaluate", builder_token)
    check("B 第二轮复验再次退回返工", status == 200 and res["state"] == "rework", f"{status} {str(res)[:120]}")
    status, loop_b = call("GET", f"/api/fde/tasks/{task_b['id']}/repair-loop", builder_token)
    check("B 的修复回路停在 no_progress（连续两轮原因相同）",
          status == 200 and loop_b["status"] == "stopped_no_progress" and loop_b["rounds"] == 2,
          str(loop_b)[:200])
    check("B 有交接建议（决策权在具名负责人）",
          loop_b["handoff"] is not None and "具名负责人" in loop_b["handoff"]["next_action"],
          str(loop_b.get("handoff"))[:160])
    status, detail_b2 = call("GET", f"/api/fde/tasks/{task_b['id']}", builder_token)
    check("B 的详情自带同一个回路投影",
          detail_b2["repair_loop"]["status"] == "stopped_no_progress", "")
    check("B 的交付摘要如实标注未收敛",
          detail_b2["delivery_summary"]["converged"] is False
          and "尚未被具名接受" in detail_b2["delivery_summary"]["markdown"], "")

    print("\n" + "=" * 64)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print("  -", name)
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
