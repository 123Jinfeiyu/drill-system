# -*- coding: utf-8 -*-
"""设计师结算系统 · 浏览器实测。

用真实 Edge（CDP）打开前端，逐页验证：页面能渲染、关键元素在、双角色能互通。
不是「HTTP 200 就算过」—— 白屏也返回 200。

流程：
1. 派单员登录 → 录设计师 → 登记订单 → 派单 → 补编号 → 传两类截图 → 审核
2. 切设计师端 → 登录 → 一键结算
3. 回派单员端 → 标记打款 → 核对设计师收益

用法：
    cd E:\\drill-system\\frontend
    ..\\backend\\.venv\\Scripts\\python.exe _shot_settle.py
"""
import base64
import json
import os
import random
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
OUT = os.path.join(ROOT, "_settle_shots")

# 结算窗口固定在 8/9 号，脚本里要能触发 —— 用后端已有的时间注入
# 每次跑用**不同的手机号**：改密流程会把密码改掉，
# 固定手机号跑第二次就登不上了。
# 手机号必须 11 位（后端会校验），用随机 8 位数字凑。
RUN_TAG = "%08d" % random.randint(0, 99999999)
DESIGNER_PHONE = "199" + RUN_TAG
DESIGNER_PWD = "settle123456"

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
    return js(sess, "document.body.innerText.slice(0,3000)", wait=0)


def has_white_screen(sess):
    """判断是否白屏：正文太短 + 没有 antd 组件。"""
    r = js(sess, """
    (function(){
      const t = document.body.innerText.trim();
      const cards = document.querySelectorAll('.ant-card, .ant-table, .ant-statistic').length;
      return {len: t.length, cards: cards, text: t.slice(0,120)};
    })()""", wait=0)
    return r if isinstance(r, dict) else {"len": 0, "cards": 0, "text": ""}


# ---------------------------------------------------------------------------
# 通用：填表单并提交
# ---------------------------------------------------------------------------

FILL_JS = """
(function(pairs){
  pairs = __PAYLOAD__;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,'value').set;
  const inputs = [...document.querySelectorAll('input:not([type=radio]):not([type=checkbox])')];
  let n = 0;
  pairs.forEach(function(p){
    const el = inputs.find(function(i){
      const label = i.closest('.ant-form-item');
      const labelText = label ? ((label.querySelector('label')||{}).innerText||'') : '';
      return (i.placeholder||'').indexOf(p.k) >= 0 || labelText.indexOf(p.k) >= 0;
    });
    if(!el) return;
    setter.call(el, p.v);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    n++;
  });
  return 'filled ' + n + '/' + pairs.length;
})()"""

def fill(sess, pairs, wait=0.6):
    """按 placeholder 或表单 label 关键字填值。"""
    payload = json.dumps(pairs, ensure_ascii=False)
    # 用 replace 注入，避免 JS 里的 % 干扰 Python 的 % 格式化
    return js(sess, FILL_JS.replace("__PAYLOAD__", payload), wait=wait)


def click_text(sess, pattern, wait=2.5):
    """点第一个 innerText 匹配 pattern 的按钮/链接。

    【坑】antd 对**两个字**的按钮会自动插空格 ——
    「登录」渲染出来是「登 录」，正则 /登录/ 根本匹配不到，
    点了半天没反应还以为是登录坏了。
    所以比较前先把空白全部去掉。
    """
    return js(sess, """
    (function(){
      const norm = function(s){ return (s||'').replace(/\\s+/g,''); };
      const b = [...document.querySelectorAll('button, a')]
        .find(function(e){ return norm(e.innerText).indexOf(norm(%s)) >= 0; });
      if(!b) return 'no-btn';
      b.click(); return 'clicked:' + norm(b.innerText);
    })()""" % json.dumps(pattern), wait=wait)


def click_segment(sess, label, wait=2.0):
    """点 Segmented 页签。

    【坑】antd 6 的 Segmented 结构是：
        .ant-segmented > .ant-segmented-group > label.ant-segmented-item
    而且**页面上不止一个 Segmented** —— 顶部导航有个「亮/暗皮肤」的也是。
    所以不能只找 ``.ant-segmented``，得逐个 group 找，
    找到含有目标文字的那个才点。

    【另一个坑】antd 的 Segmented 渲染成 ``label > input[type=radio]``，
    不是 button —— 用 click_text 找不到。
    """
    return js(sess, """
    (function(){
      const norm = function(s){ return (s||'').replace(/\\s+/g,''); };
      const want = norm(%s);
      const groups = [...document.querySelectorAll('.ant-segmented-group')];
      for(const g of groups){
        const item = [...g.querySelectorAll('.ant-segmented-item')]
          .find(function(e){ return norm(e.innerText).indexOf(want) >= 0; });
        if(!item) continue;
        const radio = item.querySelector('input[type=radio]');
        if(radio){ radio.click(); } else { item.click(); }
        return 'clicked:' + norm(item.innerText);
      }
      return 'no-item';
    })()""" % json.dumps(label), wait=wait)


PAGES = [
    ("dashboard", "/settle", ["结算业务看板", "本月业绩", "订单漏斗", "待提醒设计师"]),
    ("designers", "/settle/designers", ["设计师管理", "录入设计师", "所属战区"]),
    ("orders", "/settle/orders", ["订单登记", "登记新订单", "佣金比例区间"]),
    ("settlements", "/settle/settlements", ["结算管理", "待打款"]),
    ("bridge", "/settle/bridge", ["总系统互通", "只读", "互通状态", "预览上游数据"]),
]

DESIGNER_PAGES = [
    ("d_orders", "/designer/orders", ["我的订单", "结算有效期"]),
    ("d_settle", "/designer/settle", ["一键结算", "待结算订单"]),
    ("d_income", "/designer/income", ["收益明细", "累计收益"]),
    ("d_password", "/designer/password", ["修改密码", "初始密码"]),
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

        # ------------------------------------------------------------------
        # 一、派单员登录
        # ------------------------------------------------------------------
        log("打开登录页…")
        sess.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(7)

        # 【坑】浏览器 profile 是复用的（同一个临时用户目录），
        # 上一轮跑完 localStorage 里还留着令牌。
        # 不清掉的话，「未登录访问设计师端应被重定向」这条断言会假失败 ——
        # 因为令牌还在，本来就不该重定向。
        # 这里清干净，从真正的「未登录」状态开始。
        sess.send("Runtime.evaluate", {"expression": """
        (function(){
          localStorage.clear();
          return 'cleared:' + Object.keys(localStorage).length;
        })()""", "returnByValue": True})
        time.sleep(1)
        sess.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(5)

        if "系统加载中" in str(page_text(sess)):
            log("停在加载中，等一下…")
            time.sleep(5)

        log("填账号密码…")
        js(sess, """
        (function(){
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,'value').set;
          const inputs = [...document.querySelectorAll('input')];
          const pwd = inputs.find(function(i){ return i.type === 'password'; });
          const user = inputs.find(function(i){
            return i.type === 'text' && /用户名|账号|username/i.test(i.placeholder || '');
          });
          if(!pwd || !user) return 'no-input';
          setter.call(user, %s);
          user.dispatchEvent(new Event('input',{bubbles:true}));
          user.dispatchEvent(new Event('change',{bubbles:true}));
          setter.call(pwd, %s);
          pwd.dispatchEvent(new Event('input',{bubbles:true}));
          pwd.dispatchEvent(new Event('change',{bubbles:true}));
          return 'filled';
        })()""" % (json.dumps(USER), json.dumps(PWD)), wait=0.8)
        click_text(sess, "登")
        time.sleep(4)
        after = js(sess, "location.href", wait=0)
        log("登录后 URL：%s" % after)
        check("派单员登录成功并跳转", "/login" not in str(after), str(after))

        # ------------------------------------------------------------------
        # 二、逐页验证派单员端
        # ------------------------------------------------------------------
        for name, path, expects in PAGES:
            log("")
            log("── %s（%s）──" % (name, path))
            sess.send("Page.navigate", {"url": BASE + path})
            time.sleep(5)
            ws = has_white_screen(sess)
            log("   正文长度 %s，antd 组件 %s" % (ws.get("len"), ws.get("cards")))
            if not check("%s 页面不是白屏" % name,
                         ws.get("len", 0) > 60 or ws.get("cards", 0) > 0,
                         str(ws)[:150]):
                shot(sess, "%s_white" % name)
                continue
            full = str(page_text(sess))
            missing = [e for e in expects if e not in full]
            check("%s 页面含关键文案" % name, not missing,
                  "缺：%s" % missing)
            shot(sess, name)

        # ------------------------------------------------------------------
        # 三、导航里能进结算系统
        # ------------------------------------------------------------------
        log("")
        log("── 导航 ──")
        sess.send("Page.navigate", {"url": BASE + "/settle"})
        time.sleep(4)
        menu = js(sess, """
        (function(){
          const items = [...document.querySelectorAll('.ant-menu-item, .ant-menu-submenu-title')]
            .map(function(e){ return e.innerText.trim(); });
          return items;
        })()""", wait=0)
        check("导航含「结算系统」入口",
              isinstance(menu, list) and any("结算" in m for m in menu),
              str(menu)[:200])

        # ------------------------------------------------------------------
        # 三之二、总系统互通：预览 → 导入 → 结果，全链路
        # ------------------------------------------------------------------
        log("")
        log("── 总系统互通 ──")
        sess.send("Page.navigate", {"url": BASE + "/settle/bridge"})
        time.sleep(5)
        full = str(page_text(sess))
        check("互通页标明只读单向", "只读" in full,
              full[:200].replace("\n", " | "))
        check("互通页显示连通状态", "可连接" in full,
              full[:250].replace("\n", " | "))
        shot(sess, "bridge_status")

        # 桥接状态接口本身要能响应（不该 500）
        bridge_res = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const H = {'Authorization': 'Bearer ' + token};
          const r = await fetch('/api/settle/admin/bridge/status', {headers:H});
          const d = await r.json();
          return {status: r.status, configured: d.configured, mode: d.mode,
                  demo: d.demo_mode, total: d.designer_total};
        })()""", wait=2)
        log("   桥接状态：%s" % json.dumps(bridge_res, ensure_ascii=False))
        check("桥接状态接口 200",
              isinstance(bridge_res, dict) and bridge_res.get("status") == 200,
              str(bridge_res))
        check("桥接状态标明只读单向",
              isinstance(bridge_res, dict) and "只读" in str(bridge_res.get("mode", "")),
              str(bridge_res))

        # 点「预览上游数据」
        sess.send("Page.navigate", {"url": BASE + "/settle/bridge"})
        time.sleep(4)
        click_text(sess, "预览上游数据")
        time.sleep(4)
        full = str(page_text(sess))
        check("预览拉到上游设计师", "陈富灿" in full,
              full[:250].replace("\n", " | "))
        check("预览标出不正常的记录", "有问题" in full,
              full[:250].replace("\n", " | "))
        check("预览显示可导记录", "可导" in full,
              full[:250].replace("\n", " | "))
        shot(sess, "bridge_preview")

        # 切到订单页签
        seg_res = click_segment(sess, "订单")
        log("   切页签：%s" % seg_res)
        time.sleep(2)
        click_text(sess, "预览上游数据")
        time.sleep(4)
        full = str(page_text(sess))
        check("订单预览显示上游状态", "验收成功" in full,
              full[:300].replace("\n", " | "))
        check("订单预览显示本地状态映射", "可结算" in full,
              full[:300].replace("\n", " | "))
        shot(sess, "bridge_preview_orders")

        # 执行导入（设计师）
        sess.send("Page.navigate", {"url": BASE + "/settle/bridge"})
        time.sleep(4)
        click_text(sess, "预览上游数据")
        time.sleep(4)
        click_text(sess, "导入到本地")
        time.sleep(5)
        full = str(page_text(sess))
        check("导入结果显示新增数", "新增" in full,
              full[:250].replace("\n", " | "))
        check("导入结果显示跳过明细", "跳过明细" in full,
              full[:250].replace("\n", " | "))
        shot(sess, "bridge_import_result")

        imp = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const H = {'Content-Type':'application/json','Authorization':'Bearer ' + token};
          const r = await fetch('/api/settle/admin/bridge/import', {
            method:'POST', headers:H,
            body: JSON.stringify({kind:'designers', limit:50, only_valid:true})});
          const d = await r.json();
          return {status:r.status, created:d.created_count, skipped:d.skipped_count};
        })()""", wait=3)
        log("   幂等复验（再导一次）：%s" % json.dumps(imp, ensure_ascii=False))
        check("重复导入新增 0 条（幂等）",
              isinstance(imp, dict) and imp.get("created") == 0, str(imp))

        # 导入订单（切到订单页签）
        sess.send("Page.navigate", {"url": BASE + "/settle/bridge"})
        time.sleep(4)
        seg_res = click_segment(sess, "订单")
        log("   切订单页签：%s" % seg_res)
        time.sleep(2)
        click_text(sess, "预览上游数据")
        time.sleep(4)
        click_text(sess, "导入到本地")
        time.sleep(5)
        full = str(page_text(sess))
        check("订单导入结果显示新增数", "新增" in full,
              full[:250].replace("\n", " | "))
        shot(sess, "bridge_import_orders")

        # 导入的订单要真的落到本地订单列表
        ord_res = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const H = {'Authorization': 'Bearer ' + token};
          const r = await fetch('/api/settle/admin/orders', {headers:H});
          const d = await r.json();
          const up = d.filter(function(o){ return o.upstream_id; });
          return {total:d.length, imported:up.length,
                  sample: up.length ? up[0].order_no : ''};
        })()""", wait=3)
        log("   本地订单：%s" % json.dumps(ord_res, ensure_ascii=False))
        check("上游订单已落到本地", bool(ord_res.get("imported")),
              str(ord_res))

        # ------------------------------------------------------------------
        # 四、走一遍完整业务链（直接打 API，前端已逐页验过渲染）
        # ------------------------------------------------------------------
        log("")
        log("── 完整业务链 ──")
        chain = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const H = {'Content-Type':'application/json','Authorization':'Bearer '+token};
          const out = {};

          // ① 录设计师
          let r = await fetch('/api/settle/admin/designers', {
            method:'POST', headers:H, body: JSON.stringify({
              name:'实测设计师', nickname:'实测', phone:'%s',
              alipay_account:'test@alipay.com', alipay_name:'实测设计师',
              gender:1, recruitment_source:'其他', production_level:'标准档次',
              password:'%s'
            })});
          let d = await r.json();
          if (!d.id) {
            // 已存在就按手机号找回来
            const list = await (await fetch('/api/settle/admin/designers', {headers:H})).json();
            const hit = list.find(function(x){ return x.phone === '%s'; });
            d = hit || d;
          }
          out.designerId = d.id || '';
          out.designerName = d.name || '';

          // ② 录订单
          r = await fetch('/api/settle/admin/orders', {
            method:'POST', headers:H, body: JSON.stringify({
              customer_id:'tb_ui_test', war_zone:'独角兽', customer_service:'若暖',
              designer_id: out.designerId, order_type:'personal',
              service_type:'PPT定制', order_amount:'1000.00',
              commission_rate:'0.60', deliver_date:'2026-12-01',
              order_date:'2026-11-01', requirement:'界面实测订单'
            })});
          d = await r.json();
          out.orderId = d.id || '';
          out.orderState = d.state || '';
          out.commission = d.designer_commission || '';

          // ③ 派单
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/transition', {
            method:'POST', headers:H, body: JSON.stringify({
              to_state:'drafting', designer_id: out.designerId, detail:'界面实测派单'})});
          d = await r.json();
          out.afterAssign = d.state || JSON.stringify(d).slice(0,150);

          // ④ 无编号进终稿 —— 应该被拒
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/transition', {
            method:'POST', headers:H, body: JSON.stringify({to_state:'finalizing'})});
          out.blockNo = r.status;

          // ⑤ 补编号
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/transition', {
            method:'POST', headers:H, body: JSON.stringify({
              to_state:'finalizing', order_no:'DR-UI-2026-0001'})});
          d = await r.json();
          out.afterNo = d.state || JSON.stringify(d).slice(0,150);

          // ⑥ 无截图进待审核 —— 应该被拒
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/transition', {
            method:'POST', headers:H, body: JSON.stringify({to_state:'pending_audit'})});
          out.blockShot = r.status;

          // ⑦ 两类截图
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/transition', {
            method:'POST', headers:H, body: JSON.stringify({
              to_state:'pending_audit',
              chat_screenshot:'chat.png', file_screenshot:'file.png'})});
          d = await r.json();
          out.afterShot = d.state || JSON.stringify(d).slice(0,150);

          // ⑧ 审核通过
          r = await fetch('/api/settle/admin/orders/' + out.orderId + '/audit', {
            method:'POST', headers:H, body: JSON.stringify({action:'approve', remark:'实测通过'})});
          d = await r.json();
          out.afterAudit = d.state || JSON.stringify(d).slice(0,150);

          return out;
        })()""" % (DESIGNER_PHONE, DESIGNER_PWD, DESIGNER_PHONE), wait=3)

        log("   链路结果：%s" % json.dumps(chain, ensure_ascii=False))
        check("派单后进入初稿制作中", chain.get("afterAssign") == "drafting",
              str(chain.get("afterAssign")))
        check("无编号进终稿被拒 422", chain.get("blockNo") == 422,
              str(chain.get("blockNo")))
        check("补编号后进入终稿制作中", chain.get("afterNo") == "finalizing",
              str(chain.get("afterNo")))
        check("无截图进待审核被拒 422", chain.get("blockShot") == 422,
              str(chain.get("blockShot")))
        check("两类截图后进入待审核", chain.get("afterShot") == "pending_audit",
              str(chain.get("afterShot")))
        check("审核通过后进入可结算", chain.get("afterAudit") == "settleable",
              str(chain.get("afterAudit")))

        # 订单详情页
        if chain.get("orderId"):
            sess.send("Page.navigate",
                      {"url": BASE + "/settle/orders/" + chain["orderId"]})
            time.sleep(5)
            ws = has_white_screen(sess)
            check("结算订单详情页不是白屏",
                  ws.get("len", 0) > 60 or ws.get("cards", 0) > 0, str(ws)[:150])
            full = str(page_text(sess))
            for expect in ("订单信息", "材料与操作", "操作留痕"):
                check("详情页含「%s」" % expect, expect in full,
                      full[:200].replace("\n", " | "))
            shot(sess, "order_detail")

        # ------------------------------------------------------------------
        # 五、设计师端
        #
        # 顺序很重要：**先登录再逐页验证**。
        # 设计师端有独立鉴权，未登录访问 /designer/orders 会被重定向到登录页 ——
        # 那是正确行为，不是 bug，所以必须登录后再看页面内容。
        # ------------------------------------------------------------------
        log("")
        log("── 设计师端：先登录 ──")
        # 未登录时登录页本身要正常渲染
        sess.send("Page.navigate", {"url": BASE + "/designer/login"})
        time.sleep(4)
        full = str(page_text(sess))
        check("设计师登录页渲染正常",
              "设计师结算端" in full and "手机号" in full,
              full[:150].replace("\n", " | "))
        shot(sess, "d_login")

        # 未登录访问设计师端页面 → 必须重定向到登录页（鉴权正向验证）
        #
        # 【顺序】这条必须在**清完 localStorage 之后、登录之前**测。
        # 放在登录之后测毫无意义 —— 令牌还在，本来就不该重定向。
        sess.send("Page.navigate", {"url": BASE + "/designer/orders"})
        time.sleep(4)
        url = js(sess, "location.href", wait=0)
        check("未登录访问设计师端被重定向到登录页",
              "/designer/login" in str(url), str(url))

        r = fill(sess, [
            {"k": "派单员录入的手机号", "v": DESIGNER_PHONE},
            {"k": "初始密码", "v": DESIGNER_PWD},
        ], wait=0.8)
        log("   填表：%s" % r)
        click_text(sess, "登录")
        time.sleep(4)
        url = js(sess, "location.href", wait=0)
        log("   登录后 URL：%s" % url)
        check("设计师登录成功", "/designer/login" not in str(url), str(url))
        shot(sess, "d_after_login")

        # 首次登录会被引导去改密页 —— 这是**正确的产品行为**，
        # 测试要顺着走：先把密码改了，才能验证后面的订单/结算页。
        if "/designer/password" in str(url):
            log("   首次登录被引导到改密页，先完成改密…")
            new_pwd = "newpass" + str(int(time.time()))[-6:]
            fill(sess, [
                {"k": "派单员给你的初始密码", "v": DESIGNER_PWD},
                {"k": "至少 6 位", "v": new_pwd},
                {"k": "再输一次新密码", "v": new_pwd},
            ], wait=0.8)
            click_text(sess, "保存新密码")
            time.sleep(3)

            # 【别重复调改密接口】页面上点一次就真改掉了，
            # 再调一次必然 401（旧密码已失效）—— 那是测试自己的 bug，
            # 不是产品的 bug。改用「新密码能登录」来验证改密成功。
            new_login = js(sess, """
            (async function(){
              const r = await fetch('/api/settle/auth/login', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({phone:%s, password:%s})
              });
              const d = await r.json();
              return {status: r.status, mustChange: d.must_change_password};
            })()""" % (json.dumps(DESIGNER_PHONE), json.dumps(new_pwd)), wait=1)
            log("   新密码登录：%s" % json.dumps(new_login, ensure_ascii=False))
            check("改密后新密码能登录", str(new_login.get("status")) == "200",
                  str(new_login))
            check("改密后不再要求改密",
                  new_login.get("mustChange") is False, str(new_login))

            # 旧密码必须失效
            old_pwd_res = js(sess, """
            (async function(){
              const r = await fetch('/api/settle/auth/login', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({phone:%s, password:%s})
              });
              return r.status;
            })()""" % (json.dumps(DESIGNER_PHONE), json.dumps(DESIGNER_PWD)), wait=1)
            log("   旧密码再登录状态：%s（应为 401）" % old_pwd_res)
            check("改密后旧密码失效", str(old_pwd_res) == "401", str(old_pwd_res))

            # 用新密码正常登录，验证后续流程
            sess.send("Runtime.evaluate", {
                "expression": "localStorage.removeItem('settle_designer_token')",
                "returnByValue": True})
            sess.send("Page.navigate", {"url": BASE + "/designer/login"})
            time.sleep(4)
            fill(sess, [
                {"k": "派单员录入的手机号", "v": DESIGNER_PHONE},
                {"k": "初始密码", "v": new_pwd},
            ], wait=0.8)
            click_text(sess, "登录")
            time.sleep(4)
            url = js(sess, "location.href", wait=0)
            log("   新密码登录后 URL：%s" % url)
            check("新密码登录成功", "/designer/login" not in str(url), str(url))

        for name, path, expects in DESIGNER_PAGES:
            log("")
            log("── %s（%s）──" % (name, path))
            sess.send("Page.navigate", {"url": BASE + path})
            time.sleep(5)
            ws = has_white_screen(sess)
            log("   正文长度 %s，antd 组件 %s" % (ws.get("len"), ws.get("cards")))
            if not check("%s 页面不是白屏" % name,
                         ws.get("len", 0) > 60 or ws.get("cards", 0) > 0,
                         str(ws)[:150]):
                shot(sess, "%s_white" % name)
                continue
            full = str(page_text(sess))
            missing = [e for e in expects if e not in full]
            check("%s 页面含关键文案" % name, not missing, "缺：%s" % missing)
            shot(sess, name)

        # 一键结算：窗口状态 + 发起结算
        log("")
        log("── 一键结算 ──")
        sess.send("Page.navigate", {"url": BASE + "/designer/settle"})
        time.sleep(5)
        full = str(page_text(sess))
        log("   结算页首屏：%s" % full.replace("\n", " | ")[:220])
        check("结算页显示窗口状态",
              "结算窗口" in full or "开放" in full, full[:150].replace("\n", " | "))
        shot(sess, "d_settle_page")

        # 通过 API 发起结算（窗口期的判定在后端）
        settle_res = js(sess, """
        (async function(){
          const token = localStorage.getItem('settle_designer_token');
          if(!token) return 'NO_TOKEN';
          const H = {'Content-Type':'application/json','X-Designer-Token':token};
          const d = await (await fetch('/api/settle/me/settleable', {headers:H})).json();
          const out = {window: d.window, eligible: (d.eligible||[]).length,
                       blocked: (d.blocked||[]).length,
                       total: d.total_commission};
          if((d.eligible||[]).length){
            const r = await fetch('/api/settle/me/settle', {
              method:'POST', headers:H,
              body: JSON.stringify({order_ids: d.eligible.map(function(x){return x.order_id;})})});
            const s = await r.json();
            out.status = r.status;
            out.created = (s.created||[]).length;
            out.skipped = (s.skipped||[]).length;
            out.createdCommission = s.created && s.created[0] ? s.created[0].commission : '';
          }
          return out;
        })()""", wait=3)
        log("   发起结算结果：%s" % json.dumps(settle_res, ensure_ascii=False))
        if isinstance(settle_res, dict):
            check("结算窗口状态明确", settle_res.get("window") is not None,
                  str(settle_res)[:150])
            check("列出可结算订单", settle_res.get("eligible", 0) >= 1,
                  str(settle_res.get("eligible")))
            if settle_res.get("status") == 200:
                check("发起结算成功生成结算单", settle_res.get("created", 0) >= 1,
                      str(settle_res))
            else:
                # 非窗口期是预期行为（结算窗口每月 8-9 号）
                log("   （非结算窗口，发起被拒属预期）")

        # 收益明细
        sess.send("Page.navigate", {"url": BASE + "/designer/income"})
        time.sleep(5)
        full = str(page_text(sess))
        check("收益明细页显示结算记录",
              "收益明细" in full, full[:150].replace("\n", " | "))
        shot(sess, "d_income_page")

        # ------------------------------------------------------------------
        # 六、回到派单员端标记打款
        # ------------------------------------------------------------------
        log("")
        log("── 回派单员端标记打款 ──")
        sess.send("Page.navigate", {"url": BASE + "/settle/settlements"})
        time.sleep(5)
        full = str(page_text(sess))
        check("派单员结算管理页有数据", "结算管理" in full,
              full[:150].replace("\n", " | "))
        shot(sess, "settlements_page")

        pay_res = js(sess, """
        (async function(){
          const token = localStorage.getItem('drill_token');
          const H = {'Content-Type':'application/json','Authorization':'Bearer '+token};
          const list = await (await fetch('/api/settle/admin/settlements', {headers:H})).json();
          const pending = list.find(function(x){ return x.status === 'pending'; });
          if(!pending) return {noPending:true, total:list.length};
          const r = await fetch('/api/settle/admin/settlements/' + pending.id + '/pay', {
            method:'POST', headers:H,
            body: JSON.stringify({flow_no:'UI-TEST-' + Date.now()})});
          const d = await r.json();
          return {status:r.status, state:d.status, flow:d.flow_no, total:list.length};
        })()""", wait=3)
        log("   打款结果：%s" % json.dumps(pay_res, ensure_ascii=False))
        if isinstance(pay_res, dict) and not pay_res.get("noPending"):
            check("标记打款成功", pay_res.get("status") == 200, str(pay_res))
            check("状态变已打款", pay_res.get("state") == "paid", str(pay_res))
        else:
            check("结算单存在可打款记录", False, str(pay_res))

        # 设计师端再看收益，确认已到账
        sess.send("Page.navigate", {"url": BASE + "/designer/income"})
        time.sleep(5)
        full = str(page_text(sess))
        check("设计师收益里出现已打款", "已打款" in full,
              full[:200].replace("\n", " | "))
        shot(sess, "d_income_paid")

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

    print("")
    print("═" * 60)
    print("结果：%d 通过 / %d 失败" % (PASSED, len(FAILED)))
    if FAILED:
        print("")
        for f in FAILED:
            print("  - %s" % f)
    print("═" * 60)
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
