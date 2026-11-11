"""Q&A 演练场完整流程测试"""
import httpx
import asyncio
import json
import sys

BASE = "http://127.0.0.1:8000"
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)


async def main():
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 1. Health
        print("=" * 60)
        print("1. 健康检查")
        r = await client.get(f"{BASE}/health")
        print(f"   Status: {r.status_code}")
        print(f"   Response: {r.json()}")

        # 2. Login
        print("\n" + "=" * 60)
        print("2. 登录 (student01 / Test@2025)")
        r = await client.post(
            f"{BASE}/api/auth/login",
            json={"username": "student01", "password": "Test@2025"},
        )
        print(f"   Status: {r.status_code}")
        if r.status_code != 200:
            print(f"   Error: {r.text[:500]}")
            return
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"   Token: {token[:30]}...")

        # 3. Categories
        print("\n" + "=" * 60)
        print("3. 获取 Q&A 演练场分类")
        r = await client.get(f"{BASE}/api/practice/categories", headers=headers)
        print(f"   Status: {r.status_code}")
        cats = r.json()
        print(f"   分类数量: {len(cats)}")
        for c in cats:
            print(f"   - {c['key']}: {c['label']}")

        # 4. Create practice session
        print("\n" + "=" * 60)
        print("4. 创建演练会话 (分类: repayment, 难度: 2)")
        r = await client.post(
            f"{BASE}/api/practice/sessions",
            json={"category": "repayment", "difficulty": 2, "max_turns": 5},
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        if r.status_code != 201:
            print(f"   Error: {r.text[:500]}")
            return
        session = r.json()
        session_id = session["id"]
        print(f"   Session ID: {session_id}")
        print(f"   人设: {session.get('persona', '')[:100]}...")
        print(f"   开场白: {session.get('opening', '')[:100]}...")

        # 5. Start practice
        print("\n" + "=" * 60)
        print("5. 启动演练 (获取开场白)")
        r = await client.post(
            f"{BASE}/api/practice/sessions/{session_id}/start", headers=headers
        )
        print(f"   Status: {r.status_code}")
        if r.status_code != 200:
            print(f"   Error: {r.text[:500]}")
            return
        reply = r.json()
        print(f"   AI 客户开场: {reply['content'][:200]}")
        print(f"   is_finished: {reply['is_finished']}")
        print(f"   next_turn: {reply['next_turn']}")

        # 6. Student reply round 1
        print("\n" + "=" * 60)
        print("6. 学员回复第1轮")
        r = await client.post(
            f"{BASE}/api/practice/sessions/{session_id}/reply",
            json={"content": "您好，请问您的订单号是多少？我帮您查询一下。"},
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        if r.status_code != 200:
            print(f"   Error: {r.text[:500]}")
            return
        reply = r.json()
        print(f"   AI 客户回复: {reply['content'][:300]}")
        print(f"   is_finished: {reply['is_finished']}")
        print(f"   next_turn: {reply['next_turn']}")

        # 7. Student reply round 2
        if not reply["is_finished"]:
            print("\n" + "=" * 60)
            print("7. 学员回复第2轮")
            r = await client.post(
                f"{BASE}/api/practice/sessions/{session_id}/reply",
                json={"content": "好的，已经查到了。您的账单还剩200元未还，可以通过线下转账到对公账户完成还款。"},
                headers=headers,
            )
            print(f"   Status: {r.status_code}")
            if r.status_code == 200:
                reply = r.json()
                print(f"   AI 客户回复: {reply['content'][:300]}")
                print(f"   is_finished: {reply['is_finished']}")
                print(f"   next_turn: {reply['next_turn']}")

        # 8. Get hints
        print("\n" + "=" * 60)
        print("8. 获取知识库提示")
        r = await client.get(
            f"{BASE}/api/practice/sessions/{session_id}/hints", headers=headers
        )
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            hints = r.json()
            print(f"   提示数量: {len(hints)}")
            for h in hints[:3]:
                print(f"   - [{h.get('title', '')}] {h.get('content', '')[:80]}...")

        # 9. Score
        print("\n" + "=" * 60)
        print("9. 结束并评分")
        r = await client.post(
            f"{BASE}/api/practice/sessions/{session_id}/score", headers=headers
        )
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            score = r.json()
            print(f"   总分: {score.get('total', 0)}")
            print(f"   准确性: {score.get('accuracy', 0)}")
            print(f"   完整度: {score.get('completeness', 0)}")
            print(f"   话术规范: {score.get('etiquette', 0)}")
            print(f"   响应速度: {score.get('responsiveness', 0)}")
            print(f"   知识使用: {score.get('knowledge_use', 0)}")
            print(f"   总结: {score.get('summary', '')[:200]}")
            print(f"   薄弱点: {score.get('weak_points', [])}")
            print(f"   建议: {score.get('suggestions', '')[:200]}")
        else:
            print(f"   Error: {r.text[:500]}")

        # 10. List sessions
        print("\n" + "=" * 60)
        print("10. 查看演练会话列表")
        r = await client.get(f"{BASE}/api/practice/sessions", headers=headers)
        print(f"   Status: {r.status_code}")
        sessions = r.json()
        print(f"   会话数量: {len(sessions)}")
        for s in sessions[:3]:
            print(f"   - [{s['id'][:8]}] {s['category']} | 状态:{s['status']} | 轮次:{s['current_turn']}")

        # 11. List scores
        print("\n" + "=" * 60)
        print("11. 查看评分列表")
        r = await client.get(f"{BASE}/api/practice/scores/me", headers=headers)
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            scores = r.json()
            print(f"   评分数: {len(scores)}")
            for s in scores[:3]:
                print(f"   - [{s['session_id'][:8]}] {s['category']} | 总分:{s['total']}")

        # 12. Check scenarios
        print("\n" + "=" * 60)
        print("12. 查看剧本库（含结业考核场景）")
        r = await client.get(f"{BASE}/api/scenarios", headers=headers)
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            scenarios = r.json()
            print(f"   剧本总数: {len(scenarios)}")
            for s in scenarios:
                print(f"   - [{s['code']}] {s['title']} (难度:{s['difficulty']}, 轮次:{s['max_turns']})")

        print("\n" + "=" * 60)
        print("测试完成！")


if __name__ == "__main__":
    asyncio.run(main())
