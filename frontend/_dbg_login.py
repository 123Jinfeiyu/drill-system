# -*- coding: utf-8 -*-
"""诊断：登录页填值到底有没有进 React 的表单状态。"""
import json
import os
import sys
import time

JOB_ADMIN = r"D:\666\自动采集\job-admin"
sys.path.insert(0, JOB_ADMIN)

from apps.common.edge_crawler import (  # noqa: E402
    CDP_PORT, close_page, launch_edge, new_page, _new_session_class,
)

BASE = "http://127.0.0.1:5173"
USER = "teacher01"
PWD = "Test@2025"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def js(sess, expr, wait=0.5):
    r = sess.send("Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if res.get("subtype") == "error":
        return "JS_ERROR: " + str(res.get("description"))[:300]
    time.sleep(wait)
    return res.get("value")


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
        sess.send("Page.navigate", {"url": BASE + "/login"})
        time.sleep(7)

        log("=== 1. 页面上的 input ===")
        log(str(js(sess, """
        (function(){
          const out=[];
          document.querySelectorAll('input').forEach(function(i){
            const r=i.getBoundingClientRect();
            out.push({type:i.type, ph:i.placeholder, vis:r.width>0&&r.height>0,
                      val:i.value});
          });
          return out;
        })()""", wait=0)))

        log("=== 2. 按钮 ===")
        log(str(js(sess, """
        (function(){
          const out=[];
          document.querySelectorAll('button').forEach(function(b){
            const r=b.getBoundingClientRect();
            out.push({text:(b.innerText||'').trim(), type:b.type,
                      html:b.type, vis:r.width>0&&r.height>0});
          });
          return out;
        })()""", wait=0)))

        log("=== 3. 填值（原生 setter + input/change 事件）===")
        r = js(sess, """
        (function(){
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,'value').set;
          const inputs = [...document.querySelectorAll('input')];
          const pwd = inputs.find(function(i){ return i.type==='password'; });
          const user = inputs.find(function(i){ return i.type!=='password'; });
          if(!pwd || !user) return 'no-input:' + inputs.length;
          setter.call(user, %s);
          user.dispatchEvent(new Event('input',{bubbles:true}));
          user.dispatchEvent(new Event('change',{bubbles:true}));
          setter.call(pwd, %s);
          pwd.dispatchEvent(new Event('input',{bubbles:true}));
          pwd.dispatchEvent(new Event('change',{bubbles:true}));
          return 'filled user=' + user.value + ' pwd.len=' + pwd.value.length;
        })()""" % (json.dumps(USER), json.dumps(PWD)), wait=1.0)
        log(str(r))

        log("=== 4. React 是否收到了（看 DOM 里 value 有没有真的变）===")
        log(str(js(sess, """
        (function(){
          const inputs=[...document.querySelectorAll('input')];
          return inputs.map(function(i){ return {type:i.type, val:i.value}; });
        })()""", wait=0)))

        log("=== 5. 直接调 API 登录（绕过表单）===")
        r = js(sess, """
        (async function(){
          const resp = await fetch('/api/auth/login', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({username:%s, password:%s})
          });
          const data = await resp.json();
          return {status: resp.status, keys: Object.keys(data||{}),
                  hasToken: !!(data&&data.access_token)};
        })()""" % (json.dumps(USER), json.dumps(PWD)), wait=2.0)
        log(str(r))

        log("=== 6. 点登录按钮 ===")
        r = js(sess, """
        (function(){
          const b=[...document.querySelectorAll('button')]
            .find(function(e){ return /登/.test(e.innerText||''); });
          if(!b) return 'no-btn';
          b.click(); return 'clicked:'+(b.innerText||'').trim();
        })()""", wait=4.0)
        log(str(r))
        log("URL: %s" % js(sess, "location.href", wait=0))
        log("localStorage: %s" % js(sess, """
        (function(){
          const o={};
          for(let i=0;i<localStorage.length;i++){
            const k=localStorage.key(i); o[k]=String(localStorage.getItem(k)).slice(0,30);
          }
          return o;
        })()""", wait=0))

        log("=== 7. 页面提示（有没有报错消息）===")
        log(str(js(sess, """
        (function(){
          const out=[];
          document.querySelectorAll('.ant-message, .ant-message-notice, .ant-form-item-explain-error')
            .forEach(function(e){ const t=(e.innerText||'').trim(); if(t) out.push(t); });
          return out;
        })()""", wait=0)))
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


if __name__ == "__main__":
    main()
