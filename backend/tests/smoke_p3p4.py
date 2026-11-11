"""P3/P4 修复 smoke 测试（需后端已启动在 127.0.0.1:8000，且本机 Ollama 未启动）。

覆盖：
- P3-1 回归：知识库 URL 导入 SSRF 防护（私网/非法协议被拒）
- P3-2 注册校验（弱密码/超长用户名 422）+ 登录失败限流（第 6 次 429）
- P4-3 放弃会话：剧本演练 & Q&A 演练场 cancel 端点
- P4-5 知识条目编辑（PUT）+ 站内搜索（/knowledge/search）
- P4-6 检索索引：新增后立即可被搜索命中（验证 invalidate 生效）

注意：限流断言放在**最后**执行（会对 127.0.0.1 产生 60 秒封锁），
跑完后如需继续登录测试请重启后端或等待窗口过期。
运行：./.venv/Scripts/python.exe tests/smoke_p3p4.py
"""
import sys
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

BASE = "http://127.0.0.1:8000"
PWD = "Test@2025"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((name, bool(cond), extra))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


def main() -> int:
    c = httpx.Client(timeout=30)

    print("== 0. 健康检查 & 登录 ==")
    check("GET /health = 200", c.get(f"{BASE}/health").status_code == 200)
    tok = {}
    for who in ("student01", "teacher01"):
        r = c.post(f"{BASE}/api/auth/login", json={"username": who, "password": PWD})
        check(f"登录 {who}", r.status_code == 200, r.text[:120] if r.status_code != 200 else "")
        tok[who] = r.json().get("access_token", "")
    H = {k: {"Authorization": f"Bearer {v}"} for k, v in tok.items()}

    print("== P3-2 注册校验 ==")
    r = c.post(f"{BASE}/api/auth/register", json={"username": "pw_smoke", "password": "12345678"})
    check("纯数字密码 = 422", r.status_code == 422, str(r.status_code))
    r = c.post(f"{BASE}/api/auth/register", json={"username": "pw_smoke", "password": "abcdefgh"})
    check("纯字母密码 = 422", r.status_code == 422, str(r.status_code))
    r = c.post(f"{BASE}/api/auth/register", json={"username": "x" * 65, "password": "abcd1234"})
    check("超长用户名(65) = 422", r.status_code == 422, str(r.status_code))
    r = c.post(f"{BASE}/api/auth/register", json={"username": "ab", "password": "abcd1234"})
    check("过短用户名(2) = 422", r.status_code == 422, str(r.status_code))
    uname = "p3p4_smoke"
    r = c.post(f"{BASE}/api/auth/register", json={"username": uname, "password": "Passw0rd123"})
    check("合法注册 = 201 或已存在 400", r.status_code in (201, 400), str(r.status_code))
    r = c.post(f"{BASE}/api/auth/login", json={"username": uname, "password": "Passw0rd123"})
    check(f"新账号可登录 {uname}", r.status_code == 200, str(r.status_code))
    H[uname] = {"Authorization": f"Bearer {r.json().get('access_token', '')}"}

    print("== P3-1 回归：URL 导入 SSRF 防护 ==")
    r = c.post(f"{BASE}/api/knowledge/import-url", json={"url": "http://127.0.0.1:8000/health"}, headers=H["teacher01"])
    check("导入环回地址 = 400（SSRF 拦截）", r.status_code == 400, f"{r.status_code} {r.text[:100]}")
    r = c.post(f"{BASE}/api/knowledge/import-url", json={"url": "file:///etc/passwd"}, headers=H["teacher01"])
    check("导入 file:// = 400（协议白名单）", r.status_code == 400, f"{r.status_code} {r.text[:100]}")
    r = c.post(f"{BASE}/api/knowledge/import-url", json={"url": "http://10.0.0.1/x"}, headers=H["teacher01"])
    check("导入私网 10.x = 400", r.status_code == 400, f"{r.status_code} {r.text[:100]}")

    print("== P4-5 / P4-6 知识编辑 + 站内搜索 + 索引失效 ==")
    marker = "回归验证专用标记词"
    r = c.post(
        f"{BASE}/api/knowledge",
        json={"title": f"P4 知识条目 {marker}", "content": "重复扣款处理口径的测试内容", "tags": ["P4测试"]},
        headers=H["teacher01"],
    )
    check("新增知识条目 = 201", r.status_code == 201, r.text[:120])
    kid = r.json().get("id", "")
    # P4-6：新增后立即可被搜索命中（说明写操作已失效索引）
    r = c.get(f"{BASE}/api/knowledge/search", params={"q": marker, "top_k": 5}, headers=H["teacher01"])
    hit_ids = [it["id"] for it in r.json()] if r.status_code == 200 else []
    check("新增后立即可被搜索命中（索引失效生效）", kid in hit_ids, f"{r.status_code} hits={hit_ids}")
    # P4-5：编辑
    r = c.put(f"{BASE}/api/knowledge/{kid}", json={"title": f"已编辑 {marker}"}, headers=H["teacher01"])
    check("PUT 编辑 = 200", r.status_code == 200, r.text[:120])
    check("编辑后标题已更新", r.status_code == 200 and r.json().get("title", "").startswith("已编辑"), r.text[:80])
    r = c.put(f"{BASE}/api/knowledge/{kid}", json={"title": "x" * 201}, headers=H["teacher01"])
    check("编辑超长标题 = 422", r.status_code == 422, str(r.status_code))
    r = c.put(f"{BASE}/api/knowledge/not-exist-id", json={"title": "t"}, headers=H["teacher01"])
    check("编辑不存在条目 = 404", r.status_code == 404, str(r.status_code))
    # 学生无权编辑
    r = c.put(f"{BASE}/api/knowledge/{kid}", json={"title": "hack"}, headers=H[uname])
    check("学生编辑知识 = 403", r.status_code == 403, str(r.status_code))
    r = c.delete(f"{BASE}/api/knowledge/{kid}", headers=H["teacher01"])
    check("清理测试条目 = 204", r.status_code == 204, str(r.status_code))

    print("== P4-3 剧本演练放弃 ==")
    scenarios = c.get(f"{BASE}/api/scenarios", headers=H["student01"]).json()
    r = c.post(f"{BASE}/api/sessions", json={"scenario_id": scenarios[0]["id"]}, headers=H["student01"])
    sid = r.json()["id"]
    r = c.post(f"{BASE}/api/sessions/{sid}/start", headers=H["student01"])
    check("启动剧本会话 = 200", r.status_code == 200, str(r.status_code))
    # 非属主不能放弃
    r = c.post(f"{BASE}/api/sessions/{sid}/cancel", headers=H[uname])
    check("他人放弃剧本会话 = 403", r.status_code == 403, str(r.status_code))
    # 讲师也不能代操作（与 start/reply/score 一致）
    r = c.post(f"{BASE}/api/sessions/{sid}/cancel", headers=H["teacher01"])
    check("讲师放弃剧本会话 = 403", r.status_code == 403, str(r.status_code))
    r = c.post(f"{BASE}/api/sessions/{sid}/cancel", headers=H["student01"])
    check("属主放弃剧本会话 = 200", r.status_code == 200, r.text[:120])
    check("状态变为 canceled", r.status_code == 200 and r.json().get("status") == "canceled", r.text[:80])
    r = c.post(f"{BASE}/api/sessions/{sid}/cancel", headers=H["student01"])
    check("重复放弃 = 400", r.status_code == 400, str(r.status_code))
    r = c.get(f"{BASE}/api/sessions/{sid}", headers=H["teacher01"])
    check("讲师仍可回放已放弃会话 = 200", r.status_code == 200, str(r.status_code))

    print("== P4-3 Q&A 演练场放弃 ==")
    r = c.post(
        f"{BASE}/api/practice/sessions",
        json={"category": "repayment", "difficulty": 2, "max_turns": 4},
        headers=H["student01"],
    )
    psid = r.json()["id"]
    c.post(f"{BASE}/api/practice/sessions/{psid}/start", headers=H["student01"])
    r = c.post(f"{BASE}/api/practice/sessions/{psid}/cancel", headers=H[uname])
    check("他人放弃 practice 会话 = 403", r.status_code == 403, str(r.status_code))
    r = c.post(f"{BASE}/api/practice/sessions/{psid}/cancel", headers=H["student01"])
    check("属主放弃 practice 会话 = 200", r.status_code == 200, r.text[:120])
    check("practice 状态 canceled", r.status_code == 200 and r.json().get("status") == "canceled", r.text[:80])

    print("== P3-2 登录失败限流（最后执行）==")
    codes = []
    for _ in range(5):
        rr = c.post(f"{BASE}/api/auth/login", json={"username": "no_such_user", "password": "Wrong123"})
        codes.append(rr.status_code)
    check("前 5 次失败 = 401", codes == [401] * 5, str(codes))
    r = c.post(f"{BASE}/api/auth/login", json={"username": "no_such_user", "password": "Wrong123"})
    check("第 6 次 = 429（限流生效）", r.status_code == 429, str(r.status_code))
    check("返回 Retry-After 头", r.headers.get("Retry-After") == "60", r.headers.get("Retry-After", ""))

    c.close()
    failed = [x for x in results if not x[1]]
    print(f"\n== 结果：{len(results) - len(failed)}/{len(results)} 通过 ==")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
