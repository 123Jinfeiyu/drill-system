# -*- coding: utf-8 -*-
"""OPC 一人公司系统 · 浏览器实测。

用真实 Edge（CDP）打开前端，逐页验证：页面能渲染、关键元素在、菜单能进。
不是「HTTP 200 就算过」—— 白屏也返回 200。

用法：
    cd E:\\drill-system\\frontend
    ..\\backend\\.venv\\Scripts\\python.exe _shot_opc.py
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
# CDP 控制在 job-admin 项目里（apps.common.edge_crawler），
# 借它的模块用 —— 不在 FDE 里重复造一个浏览器控制层。
JOB_ADMIN = r"D:\666\自动采集\job-admin"
sys.path.insert(0, JOB_ADMIN)

from apps.common.edge_crawler import (  # noqa: E402
    CDP_PORT, close_page, launch_edge, new_page, _new_session_class,
)

BASE = "http://127.0.0.1:5173"
USER = "teacher01"
PWD = "Test@2025"
OUT = os.path.join(ROOT, "_opc_shots")

PASSED = 0
FAILED = []


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def check(name, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        log("  [OK]   %s" % name)
    else:
        FAILED.append("%s — %s" % (name, detail))
        log("  [FAIL] %s  (%s)" % (name, detail))
    return bool(cond)


def js(sess, expr, wait=0.5):
    r = sess.send("Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if res.get("subtype") == "error":
        return "JS_ERROR: " + str(res.get("description"))[:300]
    time.sleep(wait)
    return res.get("value")


def shot(sess, name):
    try:
        import base64
        r = sess.send("Page.captureScreenshot", {"format": "png"})
        data = r.get("data")
        if not data:
            return
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, "%s.png" % name)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        log("       截图：%s" % path)
    except Exception as e:
        log("       截图失败：%s" % str(e)[:100])


def page_text(sess):
    return js(sess, "document.body.innerText.slice(0,2000)", wait=0)


def has_white_screen(sess):
    """判断是否白屏：正文太短 + 没有 antd 组件。"""
    r = js(sess, """
    (function(){
      const t = document.body.innerText.trim();
      const cards = document.querySelectorAll('.ant-card, .ant-table, .ant-statistic').length;
      return {len: t.length, cards: cards, text: t.slice(0,120)};
    })()""", wait=0)
    return r if isinstance(r, dict) else {"len": 0, "cards": 0, "text": ""}


PAGES = [
    ("opc", "/opc", ["撮合看板", "待派单", "订单漏斗"]),
    ("orders", "/opc/orders", ["新建订单", "订单编号"]),
    ("designers", "/opc/designers", ["添加设计师", "擅长"]),
    ("stores", "/opc/stores", ["添加店铺", "结算周期"]),
    ("settlements", "/opc/settlements", ["一键生成结算单", "待结算"]),
    ("rules", "/opc/rules", ["分账规则", "试算器"]),
]


def main():
    proc = launch_edge(CDP_PORT, log=log, headless="hidden")
    sess_cls = _new_session_class()
    target = None
    try:
        target = new_page("about:blank", CDP_PORT)
        sess = sess_cls(target["webSocketDebuggerUrl"])
        sess.send("Page.enable")
        sess.send("Runtime.enable")
        sess.send("Network.enable")
        sess.send("Emulation.setDeviceMetricsOverride", {
            "width": 1680, "height": 1050, "deviceScaleFactor": 1, "mobile": False})

        # ---- 登录 ----
        log("打开登录页…")
        sess.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(7)
        txt = page_text(sess)
        if "系统加载中" in str(txt):
            log("停在加载中，等一下…")
            time.sleep(5)
        log("填账号密码…")
        # 【踩过的坑】不能用 `type !== 'password'` 找账号框 ——
        # 登录页上方 Segmented（登录/注册）也是 input[type=radio]，
        # 会被误当成账号框，值填到 radio 上，React 表单状态仍是空，
        # 点登录只会报「请输入账号」。必须按 placeholder 精确匹配。
        js(sess, """
        (function(){
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,'value').set;
          const inputs = [...document.querySelectorAll('input')];
          const pwd = inputs.find(function(i){ return i.type === 'password'; });
          const user = inputs.find(function(i){
            return i.type === 'text' && /用户名|账号|username/i.test(i.placeholder || '');
          });
          if(!pwd || !user) {
            return 'no-input:' + JSON.stringify(inputs.map(function(i){
              return {t:i.type, p:i.placeholder};
            }));
          }
          setter.call(user, %s);
          user.dispatchEvent(new Event('input',{bubbles:true}));
          user.dispatchEvent(new Event('change',{bubbles:true}));
          setter.call(pwd, %s);
          pwd.dispatchEvent(new Event('input',{bubbles:true}));
          pwd.dispatchEvent(new Event('change',{bubbles:true}));
          return 'filled user=' + user.value + ' pwd.len=' + pwd.value.length;
        })()""" % (json.dumps(USER), json.dumps(PWD)), wait=0.8)
        js(sess, """
        (function(){
          const b = [...document.querySelectorAll('button')]
            .find(function(e){ return /登/.test(e.innerText||''); });
          if(!b) return 'no-btn';
          b.click(); return 'clicked';
        })()""", wait=4)
        after = js(sess, "location.href", wait=0)
        log("登录后 URL：%s" % after)
        check("登录成功并跳转", "/login" not in str(after), str(after))

        # ---- 逐页验证 ----
        for name, path, expects in PAGES:
            log("")
            log("── %s（%s）──" % (name, path))
            sess.send("Page.navigate", {"url": BASE + path})
            time.sleep(5)
            ws = page_white = has_white_screen(sess)
            body = str(ws.get("text", ""))
            log("   正文长度 %s，antd 组件 %s" % (ws.get("len"), ws.get("cards")))
            log("   首屏：%s" % body.replace("\n", " | ")[:150])
            if not check("%s 页面不是白屏" % name,
                         ws.get("len", 0) > 60 or ws.get("cards", 0) > 0,
                         str(ws)[:150]):
                shot(sess, "%s_white" % name)
                continue
            full = str(page_text(sess))
            missing = [e for e in expects if e not in full]
            check("%s 页面含关键文案 %s" % (name, expects),
                  not missing, "缺：%s" % missing)
            shot(sess, name)

        # ---- 订单详情页 ----
        log("")
        log("── 订单详情页 ──")
        sess.send("Page.navigate", {"url": BASE + "/opc/orders"})
        time.sleep(5)
        # 先造一单，保证详情页有数据
        created = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const body = {
            order_sn: 'OP-UI-' + Date.now(),
            title: '界面实测订单',
            order_commission: '800',
            spec_snapshot: '# 订单需求单\\n\\n## 目标\\n做主图\\n\\n## 范围\\n5 张\\n\\n## 非目标\\n不做详情页\\n\\n## 约束\\n改稿不超 2 轮\\n\\n## 验收标准\\n尺寸达标\\n\\n## 完成定义\\n客户确认\\n'
          };
          const r = await fetch('/api/opc/orders', {
            method:'POST',
            headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
            body: JSON.stringify(body)
          });
          const d = await r.json();
          return d.id || ('ERR:' + JSON.stringify(d).slice(0,120));
        })()""", wait=3)
        log("   造单结果：%s" % created)
        if created and not str(created).startswith("ERR"):
            sess.send("Page.navigate", {"url": BASE + "/opc/orders/" + created})
            time.sleep(5)
            ws = has_white_screen(sess)
            check("订单详情页不是白屏",
                  ws.get("len", 0) > 60 or ws.get("cards", 0) > 0, str(ws)[:150])
            full = str(page_text(sess))
            for expect in ("履约进度", "交付证据链", "结算门禁", "返工回路"):
                check("详情页含「%s」" % expect, expect in full,
                      full[:200].replace("\n", " | "))
            shot(sess, "order_detail")

        # ---- 菜单里能进 OPC ----
        log("")
        log("── 导航 ──")
        sess.send("Page.navigate", {"url": BASE + "/opc"})
        time.sleep(4)
        menu = js(sess, """
        (function(){
          const items = [...document.querySelectorAll('.ant-menu-item, .ant-menu-submenu-title')]
            .map(function(e){ return e.innerText.trim(); });
          return items;
        })()""", wait=0)
        check("导航含「OPC 撮合」入口",
              isinstance(menu, list) and any("OPC" in m for m in menu),
              str(menu)[:200])

    finally:
        if target:
            try:
                close_page(target["id"], CDP_PORT)
            except Exception:
                pass
        try:
            proc.terminate()
        except Exception:
            pass

    log("")
    log("=" * 66)
    log(f"通过 {PASSED} 项，失败 {len(FAILED)} 项")
    for f in FAILED:
        log("  [FAIL] %s" % f)
    log("=" * 66)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
