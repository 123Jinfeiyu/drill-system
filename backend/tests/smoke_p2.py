"""P2 修复 smoke 测试（需后端已启动在 127.0.0.1:8000，且本机 Ollama 未启动）

覆盖：
- P2-1 回复/评分共享模块（reply_engine / score_utils）导入与容错行为回归
- P2-2 _strip_reasoning 未闭合 <think> 标签处理
- P2-3 requirements.txt 声明 bs4、移除 passlib；venv 可导入 bs4
- P2-4 practice_scores 表含 suggestions / business_summary 列（轻量迁移）
- P2-5 并发评分幂等（两个并发 score 请求 → 200 且仅 1 条评分记录）
- 回归：practice 会话创建（LLM 挂时走人设兜底）、讲师回放学员 practice 会话
运行：./.venv/Scripts/python.exe tests/smoke_p2.py
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import httpx

# 直接以文件路径运行时把 backend 根目录加入 sys.path，保证 `from app...` 可导入
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

BASE = "http://127.0.0.1:8000"
PWD = "Test@2025"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    results.append((name, bool(cond), extra))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))


async def main() -> int:
    # ===== P2-2：_strip_reasoning（纯函数单测，不依赖服务端）=====
    print("== P2-2 _strip_reasoning ==")
    from app.services.llm_client import _strip_reasoning

    check("成对标签剔除", _strip_reasoning("<think>推理</think>你好") == "你好",
          _strip_reasoning("<think>推理</think>你好"))
    check("未闭合 <think> 丢弃推理（原 Bug 场景）",
          _strip_reasoning("<think>这是没写完的推理过程...") == "",
          repr(_strip_reasoning("<think>这是没写完的推理过程...")))
    check("孤儿 </think>（省略起始标签）取其后正文",
          _strip_reasoning("模型推理...</think>最终回答") == "最终回答",
          _strip_reasoning("模型推理...</think>最终回答"))
    check("普通文本不受影响", _strip_reasoning("  你好呀  ") == "你好呀")
    check("成对+未闭合混合", _strip_reasoning("a<think>x</think>b<think>残缺") == "ab",
          repr(_strip_reasoning("a<think>x</think>b<think>残缺")))

    # ===== P2-1：score_utils 容错（含 practice 侧原先缺失的嵌套/wrapper 容错）=====
    print("== P2-1 score_utils 容错提取 ==")
    from app.services.score_utils import extract_score, pick, unwrap

    raw = {"result": {"scores": {"准确性": 88}, "summary": "ok", "weak_points": ["x"]}}
    inner = unwrap(raw)
    check("wrapper+嵌套中文别名提取", extract_score(inner, "accuracy") == 88.0,
          str(extract_score(inner, "accuracy")))
    check("pick 中文别名", pick(inner, ["summary", "总结"], default="") == "ok")
    from app.services.reply_engine import generate_reply_text  # noqa: F401 导入即可
    check("reply_engine 可导入", True)

    # ===== P2-3：requirements 声明 =====
    print("== P2-3 requirements.txt ==")
    req = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    check("声明 beautifulsoup4", "beautifulsoup4" in req)
    # passlib 允许出现在注释说明里，但不能有实际的依赖声明行
    check("移除 passlib", not any(ln.strip().startswith("passlib") for ln in req.splitlines()))
    try:
        import bs4  # noqa: F401
        check("venv 可导入 bs4", True)
    except ImportError:
        check("venv 可导入 bs4", False)

    # ===== P2-4：轻量迁移列检查（服务端启动时已执行 init_db）=====
    print("== P2-4 practice_scores 列 ==")
    conn = sqlite3.connect(str(BACKEND_DIR / "drill.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(practice_scores)")}
    conn.close()
    check("含 suggestions 列", "suggestions" in cols, str(sorted(cols)))
    check("含 business_summary 列", "business_summary" in cols)

    # ===== 接口回归 + P2-5 =====
    async with httpx.AsyncClient(timeout=30) as c:
        tok = {}
        for who in ("student01", "teacher01"):
            r = await c.post(f"{BASE}/api/auth/login", json={"username": who, "password": PWD})
            tok[who] = r.json()["access_token"]
        H = {k: {"Authorization": f"Bearer {v}"} for k, v in tok.items()}

        print("== P2-1 回归：practice 会话创建（LLM 挂 → 人设兜底）==")
        r = await c.post(f"{BASE}/api/practice/sessions",
                         json={"category": "repayment", "difficulty": 2, "max_turns": 4},
                         headers=H["student01"])
        check("创建 practice 会话 = 201（人设兜底不阻断）", r.status_code == 201, r.text[:120])
        pid = r.json()["id"]
        check("人设为兜底文案", "客户" in r.json()["persona"], r.json()["persona"][:40])
        r = await c.post(f"{BASE}/api/practice/sessions/{pid}/start", headers=H["student01"])
        check("启动 practice 会话 = 200", r.status_code == 200)

        n0 = len((await c.get(f"{BASE}/api/practice/sessions/{pid}/messages", headers=H["student01"])).json())
        r = await c.post(f"{BASE}/api/practice/sessions/{pid}/reply",
                         json={"content": "您好，请问具体是哪一笔重复扣款？"},
                         headers=H["student01"])
        check("LLM 挂时 reply = 5xx（单事务回滚，P1-2 行为保持）", r.status_code >= 500, str(r.status_code))
        n1 = len((await c.get(f"{BASE}/api/practice/sessions/{pid}/messages", headers=H["student01"])).json())
        check("失败后消息数不变", n1 == n0, f"{n0} -> {n1}")

        print("== P1-1 回归：讲师回放学员 practice 会话 ==")
        r = await c.get(f"{BASE}/api/practice/sessions/{pid}", headers=H["teacher01"])
        check("讲师读 practice 会话 = 200", r.status_code == 200, str(r.status_code))
        r = await c.get(f"{BASE}/api/practice/sessions/{pid}/messages", headers=H["teacher01"])
        check("讲师读 practice messages = 200", r.status_code == 200, str(r.status_code))

        print("== P2-5 并发评分幂等 ==")
        rs = await asyncio.gather(*[
            c.post(f"{BASE}/api/practice/sessions/{pid}/score", headers=H["student01"])
            for _ in range(2)
        ])
        check("两个并发 score 请求均 200", all(r.status_code == 200 for r in rs),
              str([r.status_code for r in rs]))
        r = await c.get(f"{BASE}/api/practice/scores/me", headers=H["student01"])
        cnt = sum(1 for s in r.json() if s["session_id"] == pid)
        check("该会话评分记录仅 1 条（无重复插入）", cnt == 1, f"{cnt} 条")
        # 再次串行评分：走更新分支，仍 1 条
        r = await c.post(f"{BASE}/api/practice/sessions/{pid}/score", headers=H["student01"])
        check("重复评分仍 200（更新分支）", r.status_code == 200, str(r.status_code))
        r = await c.get(f"{BASE}/api/practice/scores/me", headers=H["student01"])
        cnt2 = sum(1 for s in r.json() if s["session_id"] == pid)
        check("重复评分后仍仅 1 条", cnt2 == 1, f"{cnt2} 条")
        one = (await c.get(f"{BASE}/api/practice/sessions/{pid}/score", headers=H["student01"])).json()
        check("兜底评分字段结构完整", isinstance(one.get("weak_points"), list) and one.get("total") is not None,
              json.dumps({k: one.get(k) for k in ("total", "accuracy")}, ensure_ascii=False))

    failed = [x for x in results if not x[1]]
    print(f"\n== 结果：{len(results) - len(failed)}/{len(results)} 通过 ==")
    return 1 if failed else 0


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(asyncio.run(main()))
