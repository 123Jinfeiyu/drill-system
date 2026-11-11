"""P1 修复 smoke 测试（需后端已启动在 127.0.0.1:8000）

覆盖：
- P1-1 权限矩阵：学员可看自己会话 / 不可看他人会话 / 讲师可回看任何会话
- P1-2 LLM 失败时学员消息不落库（重发不重复）
- P1-3 API 时间字段带 +00:00 时区标记
运行：./.venv/Scripts/python.exe tests/smoke_p1.py
"""
import socket
import sys

import httpx

BASE = "http://127.0.0.1:8000"
PWD = "Test@2025"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((name, bool(cond), extra))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def main() -> int:
    c = httpx.Client(timeout=30)

    print("== 0. 健康检查 ==")
    r = c.get(f"{BASE}/health")
    check("GET /health = 200", r.status_code == 200)

    print("== 1. 登录 ==")
    tok = {}
    for who in ("student01", "teacher01"):
        r = c.post(f"{BASE}/api/auth/login", json={"username": who, "password": PWD})
        check(f"登录 {who}", r.status_code == 200, r.text[:120] if r.status_code != 200 else "")
        tok[who] = r.json().get("access_token", "")
    # 注册一个第二学员，用于"学员读他人会话"越权测试（注册接口返回用户对象，需再登录拿 token）
    r = c.post(f"{BASE}/api/auth/register", json={"username": "student02_smoke", "password": PWD})
    r = c.post(f"{BASE}/api/auth/login", json={"username": "student02_smoke", "password": PWD})
    check("准备第二学员 student02_smoke", r.status_code == 200, r.text[:120])
    tok["student02"] = r.json().get("access_token", "")
    H = {k: {"Authorization": f"Bearer {v}"} for k, v in tok.items()}

    print("== 2. 准备演练会话（student01）==")
    r = c.get(f"{BASE}/api/scenarios", headers=H["student01"])
    scenarios = r.json()
    check("剧本列表非空", len(scenarios) > 0)
    # P1-3：created_at 应带 UTC 时区标记（pydantic v2 对 UTC 输出 Z 后缀，等价 +00:00）
    sample_ts = scenarios[0]["created_at"]
    check("P1-3 时间带时区标记 (Z/+00:00)", sample_ts.endswith("Z") or sample_ts.endswith("+00:00"), sample_ts)

    r = c.post(f"{BASE}/api/sessions", json={"scenario_id": scenarios[0]["id"]}, headers=H["student01"])
    check("student01 创建会话", r.status_code == 201, r.text[:120])
    sid = r.json()["id"]
    r = c.post(f"{BASE}/api/sessions/{sid}/start", headers=H["student01"])
    check("student01 启动会话", r.status_code == 200, r.text[:120])
    # P1-3：started_at 带时区
    sess = c.get(f"{BASE}/api/sessions/{sid}", headers=H["student01"]).json()
    check("P1-3 started_at 带时区标记", (sess["started_at"] or "").endswith("Z") or (sess["started_at"] or "").endswith("+00:00"), str(sess["started_at"]))

    print("== 3. P1-1 权限矩阵 ==")
    n_msgs_student = len(c.get(f"{BASE}/api/sessions/{sid}/messages", headers=H["student01"]).json())
    check("学员读自己会话 messages = 200", n_msgs_student >= 1, f"{n_msgs_student} 条")

    r = c.get(f"{BASE}/api/sessions/{sid}", headers=H["student02"])
    check("学员读他人会话详情 = 403", r.status_code == 403, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/messages", headers=H["student02"])
    check("学员读他人 messages = 403（原 IDOR 已封）", r.status_code == 403, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/score", headers=H["student02"])
    check("学员读他人 score = 403（原 IDOR 已封）", r.status_code == 403, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/hints", headers=H["student02"])
    check("学员读他人 hints = 403", r.status_code == 403, str(r.status_code))

    r = c.get(f"{BASE}/api/sessions/{sid}", headers=H["teacher01"])
    check("讲师读学员会话详情 = 200（原 403 已放开）", r.status_code == 200, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/messages", headers=H["teacher01"])
    check("讲师读学员 messages = 200（可回放）", r.status_code == 200, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/hints", headers=H["teacher01"])
    check("讲师读学员 hints = 200", r.status_code == 200, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}/score", headers=H["teacher01"])
    check("讲师读学员 score（未评分）= 404 而非 403", r.status_code == 404, str(r.status_code))

    print("== 4. P1-2 LLM 失败时学员消息不落库 ==")
    if port_open("127.0.0.1", 11434):
        print("  SKIP  本机 Ollama 在运行，LLM 会真实回复，跳过失败注入断言")
    else:
        r = c.post(f"{BASE}/api/sessions/{sid}/reply", json={"content": "您好，请提供一下工单号"}, headers=H["student01"])
        check("LLM 不可用时 reply 返回 5xx", r.status_code >= 500, str(r.status_code))
        n_after = len(c.get(f"{BASE}/api/sessions/{sid}/messages", headers=H["student01"]).json())
        check("P1-2 失败后消息数不变（单事务回滚）", n_after == n_msgs_student, f"{n_msgs_student} -> {n_after}")
        sess2 = c.get(f"{BASE}/api/sessions/{sid}", headers=H["student01"]).json()
        check("P1-2 失败后轮次未推进", sess2["current_turn"] == 1, f"turn={sess2['current_turn']}")

    c.close()
    failed = [x for x in results if not x[1]]
    print(f"\n== 结果：{len(results) - len(failed)}/{len(results)} 通过 ==")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
