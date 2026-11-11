"""实战话术面板 API 级验收。

前置：后端已运行（127.0.0.1:8000），且已执行过 seed_live_scripts.py 导入话术库。
运行：./.venv/Scripts/python.exe -X utf8 tests/smoke_live.py

测的是**行为**：真实 HTTP + 真实数据库 + 真实音频文件。
重点覆盖「录音陆续补进来」这条路线上的关键行为——
往目录里丢一个 mp3，不出重启、不重新导入，接口就该立刻改口说「有录音了」。

> 顺序陷阱：本脚本只登录两次，不触发限流；但若紧接 smoke_p3p4.py 之后运行
> （它会故意制造 6 次失败登录触发 60 秒同 IP 限流），这里会 429 挂在登录那步。
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
import struct
import sys
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "audio" / "live"
DB_PATH = ROOT / "drill.db"

TMP_CODE = "smoke-audio-1"
# 最小可识别的 MPEG 帧头 + 静音数据，够 StaticFiles 当音频文件发出去
TMP_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 128

# 当场录音验收用的素材与第三方账号
RECORD_MIME = "audio/wav"
PEER_USER = "smoke_peer"
PEER_PASS = "Smoke@2025"

PASSED: list[str] = []
FAILED: list[str] = []
CREATED_SCRIPT_ID: str | None = None
PIN_TOGGLED: str | None = None
# 进场模式/排序的夹具还原目标（测试用的「开场」场景）
ENTRY_SCENE_ID: str | None = None


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


def raw_get(path: str):
    """取原始字节，用来验证音频静态服务真的在发音频而不是发 JSON。"""
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", ""), exc.read()


def make_wav(seconds: float = 0.6, freq: int = 440, rate: int = 16000) -> bytes:
    """生成一段真实的正弦 WAV。

    用真音频而不是随机字节：取回来能校验 RIFF/WAVE 头，证明这条链路
    搬的是音频文件本身，没有被谁当成文本截断过。
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            value = int(12000 * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))
    return buf.getvalue()


def post_multipart(
    path: str,
    field: str,
    filename: str,
    content: bytes,
    content_type: str,
    extra: dict[str, str] | None = None,
    token: str | None = None,
):
    """手搓 multipart：标准库没现成的，而录音上传恰好就是 multipart。"""
    boundary = "----smokelive" + uuid.uuid4().hex
    body = bytearray()
    for key, value in (extra or {}).items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
        f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
    ).encode()
    body += content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def ensure_peer() -> str | None:
    """取一个「既不是本人也不是讲师」的第三方账号，用来验证越权删除被拒。

    注册接口本来就是开放的，这里复用它建一个固定名账号；测试结束后由
    drop_peer() 直接从库里删掉，不留痕（夹具动作，口径同 smoke_fde 重置 fde_* 表）。
    """
    status, _ = call(
        "POST",
        "/api/auth/register",
        payload={"username": PEER_USER, "password": PEER_PASS, "display_name": "冒烟对端"},
    )
    if status not in (201, 400):  # 400 = 已存在，上一轮留下的
        return None
    try:
        return login(PEER_USER, PEER_PASS)
    except SystemExit:
        return None


def drop_peer() -> None:
    """把对端账号从库里删掉，避免冒烟测试在用户表里留一个可登录账号。"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM users WHERE username = ?", (PEER_USER,))
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - 清理失败不该盖掉测试结论
        print(f"  [warn] 删除对端账号失败: {exc}")


def login(username: str, password: str) -> str:
    status, body = call("POST", "/api/auth/login", payload={"username": username, "password": password})
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"登录失败 {username}: {status} {body}")
    return body["access_token"]


def section(title: str) -> None:
    print(f"\n== {title} ==")


def all_scripts(boot: dict) -> list[dict]:
    return [s for scene in boot["scenes"] for s in scene["scripts"]]


def cleanup() -> None:
    """不留垃圾：删掉测试建的话术、还原置顶、删掉测试音频文件、清掉对端账号。

    除了记账的 id，还按快捷码做一次兜底清扫——脚本中途异常退出时，
    只认 CREATED_SCRIPT_ID 会漏（实测漏过一条，下次跑就 409 挂在建话术那步）。
    进场模式与 Top 榜同样要还原：实测崩溃退出会把 auto/手动位次留到下一轮，
    「默认 silent」的断言和「只有一条进榜」的断言就都站不住了。
    """
    global ENTRY_SCENE_ID
    try:
        tok = login("teacher01", "Test@2025")
        if CREATED_SCRIPT_ID:
            call("DELETE", f"/api/live/scripts/{CREATED_SCRIPT_ID}", token=tok)
        status, hits = call("GET", f"/api/live/search?q={TMP_CODE}", token=tok)
        if status == 200 and isinstance(hits, list):
            for hit in hits:
                if str(hit.get("code", "")).startswith(TMP_CODE):
                    call("DELETE", f"/api/live/scripts/{hit['id']}", token=tok)
        if PIN_TOGGLED:
            call("POST", f"/api/live/scenes/{PIN_TOGGLED}/pin", token=tok)
        if ENTRY_SCENE_ID:
            call("POST", f"/api/live/scenes/{ENTRY_SCENE_ID}/entry-mode", token=tok,
                 payload={"mode": "silent"})
            status, detail = call("GET", f"/api/live/scenes/{ENTRY_SCENE_ID}", token=tok)
            if status == 200:
                for item in detail.get("scripts", []):
                    if item.get("manual_rank") is not None:
                        call("POST", f"/api/live/scripts/{item['id']}/reorder", token=tok,
                             payload={"position": 0})
        ENTRY_SCENE_ID = None
    except Exception as exc:  # noqa: BLE001 - 清理失败不该盖掉测试结论
        print(f"  [warn] 清理话术/置顶失败: {exc}")
    stray = AUDIO_DIR / f"{TMP_CODE}.mp3"
    if stray.exists():
        stray.unlink()
    drop_peer()


def main() -> int:
    global CREATED_SCRIPT_ID, PIN_TOGGLED, ENTRY_SCENE_ID

    print("实战话术面板 API 验收")
    student = login("student01", "Test@2025")
    teacher = login("teacher01", "Test@2025")
    # recorded_by 对外给的是**显示名**（录的人看自己名字，不是工号），
    # 所以断言要拿真实显示名比对，不能硬编码用户名。
    status, me = call("GET", "/api/auth/me", token=student)
    student_name = (me or {}).get("display_name") or "student01"

    # 夹具复位：把上一轮异常退出留下的残留先扫干净，保证本轮断言站在干净地面上
    cleanup()

    # ---------------------------------------------------------------- 鉴权
    section("鉴权")
    status, _ = call("GET", "/api/live/bootstrap")
    check("未登录访问 bootstrap 被拒 401", status == 401, f"实际 {status}")

    # ------------------------------------------------------ 面板数据完整性
    section("面板数据完整性")
    status, boot = call("GET", "/api/live/bootstrap", token=student)
    check("bootstrap 返回 200", status == 200, f"实际 {status}")
    if status != 200 or not isinstance(boot, dict):
        cleanup()
        return 1

    scenes = boot["scenes"]
    scripts = all_scripts(boot)
    check("场景数 > 0", len(scenes) > 0, str(len(scenes)))
    check("话术总数与统计一致", len(scripts) == boot["script_total"], f"{len(scripts)} vs {boot['script_total']}")
    check("四个话务阶段齐全", len(boot["phases"]) == 4)
    check(
        "每个阶段都有场景",
        all(p["scene_count"] > 0 for p in boot["phases"]),
        str([(p["key"], p["scene_count"]) for p in boot["phases"]]),
    )
    check("话术都有 code", all(s["code"] for s in scripts))
    check("话术都有正文", all(s["text"] for s in scripts))
    check("音频状态取值合法", {s["audio_status"] for s in scripts} <= {"file", "tts"})
    check("code 全局唯一", len({s["code"] for s in scripts}) == len(scripts))

    opening = next((s for s in scenes if s["name"] == "开场"), None)
    check("存在「开场」场景", opening is not None)
    if opening:
        ENTRY_SCENE_ID = opening["id"]
        # 夹具复位：上一轮异常退出可能把进场模式/手动位次留在库里，
        # 先还原，再取一份新快照，让「默认 silent」这类断言站在干净地面上
        call("POST", f"/api/live/scenes/{opening['id']}/entry-mode",
             token=student, payload={"mode": "silent"})
        status, opening = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
        # 展示序含热度排序，aa1 未必永远排第一；按 code 定位才站得住
        aa1_item = next((s for s in opening["scripts"] if s["code"] == "aa1"), None)
        check("开场问候语 aa1 在场且标记自动播报",
              bool(aa1_item) and aa1_item["auto_play"] is True,
              str(aa1_item and aa1_item["code"]))
    check(
        "每个场景恰好一条自动播报",
        all(sum(1 for s in scene["scripts"] if s["auto_play"]) == 1 for scene in scenes),
    )

    # 阶段顺序：开场必须排在业务场景之前（话务动线）
    order = [s["name"] for s in scenes]
    if "开场" in order and len(order) > 1:
        idx_support = next((i for i, s in enumerate(scenes) if s["phase"] == "support"), None)
        check(
            "开场排在任何支撑/业务场景之前",
            all(
                order.index("开场") <= i
                for i, s in enumerate(scenes)
                if s["phase"] in ("support", "business", "closing")
            )
            or idx_support is not None,
        )

    # ---------------------------------------------------------------- 搜索
    section("搜索")
    status, hits = call("GET", "/api/live/search?q=hy2", token=student)
    check("按快捷码搜索返回 200", status == 200, f"实际 {status}")
    check("快捷码精确匹配排第一", bool(hits) and hits[0]["code"] == "hy2", str(hits[:1]))
    status, hits = call("GET", "/api/live/search?q=%E7%BB%93%E6%B8%85%E8%AF%81%E6%98%8E", token=student)
    check("按中文关键词搜索有结果", status == 200 and len(hits) > 0, f"{status} / {len(hits) if isinstance(hits, list) else hits}")
    status, _ = call("GET", "/api/live/search?q=", token=student)
    check("空关键词被拒 422", status == 422, f"实际 {status}")

    # ------------------------------------------------- 音频匹配（核心路径）
    section("音频匹配：MP3 优先 + TTS 兜底")
    check("录音目录存在", AUDIO_DIR.is_dir(), str(AUDIO_DIR))

    status, created = call(
        "POST",
        f"/api/live/scenes/{opening['id']}/scripts",
        token=teacher,
        payload={"scene_id": opening["id"], "text": "这是一条用于验收的临时话术，稍后删除", "code": TMP_CODE},
    )
    check("讲师可新增话术 201", status == 201, f"{status} {created}")
    if status != 201:
        cleanup()
        return 1
    CREATED_SCRIPT_ID = created["id"]
    check("无录音时状态为 tts", created["audio_status"] == "tts", created["audio_status"])
    check("无录音时 audio_url 为空", created["audio_url"] is None)

    # -------------------------------------------- 学员 CRUD（实战口径：坐席自己维护）
    section("学员话术 CRUD：建 → 改（含改码）→ 删")
    stu_code = f"{TMP_CODE}-s"
    status, stu = call(
        "POST",
        f"/api/live/scenes/{opening['id']}/scripts",
        token=student,
        payload={"scene_id": opening["id"], "text": "学员建的话术", "code": stu_code},
    )
    check("学员可新增话术 201", status == 201, f"{status} {stu}")
    if status == 201:
        sid = stu["id"]
        status, upd = call(
            "PUT", f"/api/live/scripts/{sid}", token=student,
            payload={"text": "学员改过的话术", "label": "改标题", "code": f"{TMP_CODE}-s2"},
        )
        check("学员可编辑话术（含改快捷码）", status == 200 and upd["code"] == f"{TMP_CODE}-s2", f"{status} {upd.get('code') if isinstance(upd, dict) else upd}")
        status, dup = call(
            "PUT", f"/api/live/scripts/{sid}", token=student, payload={"code": "aa1"},
        )
        check("改码撞已有码回 409", status == 409, f"实际 {status}")
        status, _ = call("DELETE", f"/api/live/scripts/{sid}", token=student)
        check("学员可删除自己建的话术", status == 204, f"实际 {status}")
    else:
        check("学员可编辑话术（含改快捷码）", False, "前置建话术失败")
        check("改码撞已有码回 409", False, "前置建话术失败")
        check("学员可删除自己建的话术", False, "前置建话术失败")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIO_DIR / f"{TMP_CODE}.mp3").write_bytes(TMP_MP3)
    status, after = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    target = next((s for s in after["scripts"] if s["code"] == TMP_CODE), None) if status == 200 else None
    check("放入 mp3 后无需重启即识别为录音", bool(target) and target["audio_status"] == "file", str(target))
    check(
        "audio_url 指向静态目录",
        bool(target) and target["audio_url"] == f"/audio/live/{TMP_CODE}.mp3",
        str(target.get("audio_url") if target else None),
    )
    check(
        "场景已录数随之 +1",
        bool(target) and opening["recorded_count"] + 1 == after["recorded_count"],
    )

    status, ctype, body = raw_get(f"/audio/live/{TMP_CODE}.mp3")
    check("音频静态服务返回 200", status == 200, f"实际 {status}")
    check("响应确为音频类型", "audio" in (ctype or ""), ctype)
    check("音频字节完整", body == TMP_MP3, f"{len(body)} bytes")

    (AUDIO_DIR / f"{TMP_CODE}.mp3").unlink()
    status, back = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    target = next((s for s in back["scripts"] if s["code"] == TMP_CODE), None) if status == 200 else None
    check("删掉 mp3 后回落为 tts", bool(target) and target["audio_status"] == "tts")

    # ------------------------------------------------------------ 使用计数
    section("使用计数")
    before = next(s for s in back["scripts"] if s["code"] == TMP_CODE)["use_count"]
    status, used = call("POST", f"/api/live/scripts/{CREATED_SCRIPT_ID}/use", token=student)
    check("播放上报返回 200", status == 200, f"实际 {status}")
    check("使用次数 +1", status == 200 and used["use_count"] == before + 1, f"{before} -> {used.get('use_count') if isinstance(used, dict) else used}")
    status, gaps = call("GET", "/api/live/audio-gaps", token=student)
    top_codes = [g["code"] for g in gaps[:5]] if status == 200 else []
    check("待录音清单按使用频次排序（刚用过的排进前 5）", TMP_CODE in top_codes, str(top_codes))

    # --------------------------------------------------------- 当场录音链路 ---
    # 这条链路是「磁盘录音 → 库内录音 → TTS」三级判定的中间一级：
    # 坐席当场录一条，不用等音频同事，也不用重启服务。
    section("当场录音：录 → 取回 → 落库")
    audio_api = f"/api/live/scripts/{CREATED_SCRIPT_ID}/audio"

    # 幂等：先清掉上一轮可能留下的录音，否则「初始必须是 tts」站不住
    call("DELETE", audio_api, token=student)
    status, baseline = call("GET", "/api/live/bootstrap", token=student)
    check("重拉面板取录音基线 200", status == 200, f"实际 {status}")
    base_total = baseline["recorded_total"] if status == 200 else -1

    status, scene_now = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    fresh = next((s for s in scene_now["scripts"] if s["code"] == TMP_CODE), None) if status == 200 else None
    check(
        "录音字段齐备（has_audio/recording_size/recorded_by）",
        bool(fresh) and {"has_audio", "recording_size", "recorded_by"} <= set(fresh),
        str(sorted(fresh or {})),
    )
    check("未录音时是 tts", bool(fresh) and fresh["audio_status"] == "tts",
          fresh["audio_status"] if fresh else "拿不到话术")
    check("未录音时 has_audio 为假", bool(fresh) and fresh["has_audio"] is False)
    check("未录音时 audio_url 为空", bool(fresh) and not fresh["audio_url"], str(fresh.get("audio_url") if fresh else None))

    status, _, _ = raw_get(audio_api)
    check("匿名叫得到录音被拒 401", status == 401, f"实际 {status}")
    status, _, _ = raw_get(f"{audio_api}?token={student}")
    check("没有录音时取音频 404", status == 404, f"实际 {status}")
    status, _ = post_multipart("/api/live/scripts/no-such-script/audio", "file", "x.wav",
                               make_wav(0.05), RECORD_MIME, {}, student)
    check("给不存在的话术传录音 404", status == 404, f"实际 {status}")

    wav = make_wav()
    status, uploaded = post_multipart(
        audio_api, "file", f"{TMP_CODE}.wav", wav, RECORD_MIME, {"duration_ms": "600"}, student
    )
    check("学员可上传录音 200（有意开放给坐席）", status == 200, f"{status} {uploaded}")
    if status == 200:
        check("状态翻成 record", uploaded["audio_status"] == "record", uploaded["audio_status"])
        check("has_audio 变真", uploaded["has_audio"] is True)
        check("字节数已记录", uploaded["recording_size"] == len(wav),
              f"{uploaded['recording_size']} vs {len(wav)}")
        check("时长已记录", uploaded["recording_duration_ms"] == 600, str(uploaded["recording_duration_ms"]))
        check("上传者已记名（显示名）", uploaded["recorded_by"] == student_name,
              f"{uploaded['recorded_by']} vs {student_name}")
        check("audio_url 指向录音接口", (uploaded["audio_url"] or "").endswith("/audio"),
              str(uploaded["audio_url"]))

    status, ctype, got = raw_get(f"{audio_api}?token={student}")
    check("凭 ?token= 取回录音 200（<audio src> 的走法）", status == 200, f"实际 {status}")
    check("响应是音频类型", "audio" in (ctype or ""), ctype)
    check("字节与上传完全一致（真能播）", got == wav, f"{len(got)} vs {len(wav)}")
    check("取回的是合法 WAV（RIFF/WAVE 头）", got[:4] == b"RIFF" and got[8:12] == b"WAVE", repr(got[:12]))

    status, persisted = call("GET", "/api/live/bootstrap", token=student)
    scene_again = next((sc for sc in persisted["scenes"] if sc["id"] == opening["id"]), None) if status == 200 else None
    again = next((s for s in scene_again["scripts"] if s["code"] == TMP_CODE), None) if scene_again else None
    check("录制结果已落库（重拉面板仍是 record）", bool(again) and again["audio_status"] == "record",
          again["audio_status"] if again else "拿不到话术")
    check("全局已录计数 +1（库内录音计入统计）",
          status == 200 and persisted["recorded_total"] == base_total + 1,
          f"{persisted.get('recorded_total') if status == 200 else '?'} vs 基线 {base_total}")
    check("场景内已录计数同步",
          bool(scene_again) and scene_again["recorded_count"] == opening["recorded_count"] + 1,
          f"{scene_again.get('recorded_count') if scene_again else '?'} vs {opening['recorded_count']}")

    status, gaps2 = call("GET", "/api/live/audio-gaps", token=student)
    check("已录音的话术退出待录清单",
          status == 200 and TMP_CODE not in [g["code"] for g in gaps2], f"实际 {status}")

    # --------------------------------------------------------- 非法输入边界 ---
    section("当场录音：非法输入")
    status, _ = post_multipart(audio_api, "file", "empty.wav", b"", RECORD_MIME, {}, student)
    check("空音频被拒 400", status == 400, f"实际 {status}")
    oversize = b"RIFF" + b"\x00" * (8 * 1024 * 1024 + 16)
    status, _ = post_multipart(audio_api, "file", "big.wav", oversize, RECORD_MIME, {}, student)
    check("超过 8MB 被拒 413", status == 413, f"实际 {status}")
    status, _ = post_multipart(audio_api, "file", "note.txt", b"this is not audio", "text/plain", {}, student)
    check("非音频格式被拒 415", status == 415, f"实际 {status}")
    status, _ = post_multipart(audio_api, "file", "x.wav", wav, RECORD_MIME, {}, None)
    check("匿名上传被拒 401", status == 401, f"实际 {status}")
    status, untouched = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    keep = next((s for s in untouched["scripts"] if s["code"] == TMP_CODE), None) if status == 200 else None
    check("被拒的上传没有污染已有录音",
          bool(keep) and keep["audio_status"] == "record" and keep["recording_size"] == len(wav),
          str(keep))

    # --------------------------------------------------------- 重录即替换 ---
    section("当场录音：重录即替换")
    replacement = make_wav(seconds=0.3, freq=660)
    status, replaced = post_multipart(
        audio_api, "file", "again.webm", replacement, "audio/webm;codecs=opus",
        {"duration_ms": "300"}, student,
    )
    check("重录成功 200", status == 200, f"{status} {replaced}")
    check("带 codecs 参数的 MIME 被收敛（浏览器实传格式）",
          status == 200 and replaced["audio_status"] == "record", str(replaced))
    check("大小被覆盖为新值", status == 200 and replaced["recording_size"] == len(replacement),
          f"{replaced.get('recording_size') if status == 200 else '?'} vs {len(replacement)}")
    status, _, got2 = raw_get(f"{audio_api}?token={student}")
    check("取回的是新录的那一版（不是旧的）", got2 == replacement, f"{len(got2)} vs {len(replacement)}")
    status, after_replace = call("GET", "/api/live/bootstrap", token=student)
    check("重录不重复计数（一个话术只留一条）",
          status == 200 and after_replace["recorded_total"] == base_total + 1,
          f"{after_replace.get('recorded_total') if status == 200 else '?'} vs 基线 {base_total}")

    # --------------------------------------------------------- 删除权限 ---
    section("当场录音：删除权限")
    peer = ensure_peer()
    check("取得第三方账号（越权测试用）", bool(peer))
    if peer:
        status, _ = call("DELETE", audio_api, token=peer)
        check("非本人学员删除被拒 403", status == 403, f"实际 {status}")

    status, _ = call("DELETE", audio_api, token=teacher)
    check("讲师可删他人录音 204", status == 204, f"实际 {status}")
    status, uploaded2 = post_multipart(
        audio_api, "file", "own.wav", wav, RECORD_MIME, {"duration_ms": "600"}, student
    )
    check("学员再次上传 200", status == 200, f"实际 {status}")
    status, _ = call("DELETE", audio_api, token=student)
    check("本人可删自己的录音 204", status == 204, f"实际 {status}")
    status, _, _ = raw_get(f"{audio_api}?token={student}")
    check("删完取音频回落 404", status == 404, f"实际 {status}")

    status, final = call("GET", "/api/live/bootstrap", token=student)
    final_scene = next((sc for sc in final["scenes"] if sc["id"] == opening["id"]), None) if status == 200 else None
    final_item = next((s for s in final_scene["scripts"] if s["code"] == TMP_CODE), None) if final_scene else None
    check("删完状态回落 tts", bool(final_item) and final_item["audio_status"] == "tts",
          final_item["audio_status"] if final_item else "拿不到话术")
    check("删完已录计数回落到基线",
          status == 200 and final["recorded_total"] == base_total,
          f"{final.get('recorded_total') if status == 200 else '?'} vs 基线 {base_total}")
    drop_peer()

    # ---------------------------------------------------------------- 置顶
    section("置顶")
    pinned_before = opening["pinned"]
    status, toggled = call("POST", f"/api/live/scenes/{opening['id']}/pin", token=teacher)
    check("讲师可切换置顶", status == 200 and toggled["pinned"] != pinned_before, f"{status} {toggled}")
    PIN_TOGGLED = opening["id"]
    status, boot2 = call("GET", "/api/live/bootstrap", token=student)
    check("置顶场景排到最前", status == 200 and boot2["scenes"][0]["name"] == "开场", str(boot2["scenes"][:1]) if status == 200 else "")
    status, _ = call("POST", f"/api/live/scenes/{opening['id']}/pin", token=teacher)
    check("再次切换即取消置顶", status == 200)
    PIN_TOGGLED = None

    # ------------------------------------------------ 常用标签与进场模式
    section("常用标签与进场模式")
    check("场景默认进场模式为 silent（进场不出声）",
          opening.get("entry_mode", "silent") == "silent", str(opening.get("entry_mode")))
    status, _ = call("POST", f"/api/live/scenes/{opening['id']}/entry-mode",
                     token=student, payload={"mode": "nonsense"})
    check("非法进场模式被拒 422", status == 422, f"实际 {status}")
    status, mode_on = call("POST", f"/api/live/scenes/{opening['id']}/entry-mode",
                           token=student, payload={"mode": "auto"})
    check("学员可切换进场模式为 auto（面板偏好，有意开放）",
          status == 200 and mode_on["entry_mode"] == "auto", f"{status}")
    status, common_on = call("POST", f"/api/live/scripts/{CREATED_SCRIPT_ID}/common",
                             token=student, payload={"is_common": True})
    check("学员可打「常用」标签", status == 200 and common_on["is_common"] is True, f"{status}")
    status, detail = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    entry_target = next((s for s in detail["scripts"] if s["is_common"]), None) if status == 200 else None
    check("auto 模式的进场目标可被定位（打标的第一条）",
          bool(entry_target) and entry_target["id"] == CREATED_SCRIPT_ID,
          str(entry_target and entry_target["code"]))
    status, _ = call("POST", f"/api/live/scripts/{CREATED_SCRIPT_ID}/common",
                     token=student, payload={"is_common": False})
    status, detail2 = call("GET", f"/api/live/scenes/{opening['id']}", token=student)
    check("摘掉标签后没有进场目标（auto 也不播）",
          status == 200 and all(not s["is_common"] for s in detail2["scripts"]))

    # ----------------------------------------------------- 手动排序（Top 榜）
    section("手动排序（Top 榜）")
    status, scene_r = call("POST", f"/api/live/scripts/{CREATED_SCRIPT_ID}/reorder",
                           token=student, payload={"position": 1})
    codes = [s["code"] for s in scene_r["scripts"]] if status == 200 else []
    check("设为 Top1 成功且排最前", status == 200 and codes[:1] == [TMP_CODE], f"{status} {codes[:3]}")
    ranked = [s for s in scene_r["scripts"] if s["manual_rank"] is not None] if status == 200 else []
    check("只有目标进了 Top 榜（位次 1）",
          len(ranked) == 1 and ranked[0]["manual_rank"] == 1,
          str([(s["code"], s["manual_rank"]) for s in ranked]))

    aa1 = next((s for s in scene_r["scripts"] if s["code"] == "aa1"), None)
    check("场景里有开场语 aa1 可用于插队测试", aa1 is not None)
    if aa1:
        status, scene_r2 = call("POST", f"/api/live/scripts/{aa1['id']}/reorder",
                                token=student, payload={"position": 1})
        codes2 = [s["code"] for s in scene_r2["scripts"]] if status == 200 else []
        ranks2 = {s["code"]: s["manual_rank"] for s in scene_r2["scripts"] if s["manual_rank"]} if status == 200 else {}
        check("aa1 插队 Top1，原 Top1 顺延为 Top2", codes2[:2] == ["aa1", TMP_CODE], str(codes2[:3]))
        check("位次恰好是 1 和 2", ranks2 == {"aa1": 1, TMP_CODE: 2}, str(ranks2))

        status, scene_r3 = call("POST", f"/api/live/scripts/{CREATED_SCRIPT_ID}/reorder",
                                token=student, payload={"position": 0})
        codes3 = [s["code"] for s in scene_r3["scripts"]] if status == 200 else []
        tmp_item = next((s for s in scene_r3["scripts"] if s["id"] == CREATED_SCRIPT_ID), None) if status == 200 else None
        check("退出榜单后 Top1 仍是 aa1", status == 200 and codes3[:1] == ["aa1"], str(codes3[:3]))
        check("退出榜单后 manual_rank 清空", bool(tmp_item) and tmp_item["manual_rank"] is None)
        check("退出榜单后其余位次不受影响",
              status == 200 and {s["code"]: s["manual_rank"] for s in scene_r3["scripts"] if s["manual_rank"]}
              == {"aa1": 1},
              str([(s["code"], s["manual_rank"]) for s in scene_r3["scripts"]]))

        status, scene_r4 = call("POST", f"/api/live/scripts/{aa1['id']}/reorder",
                                token=student, payload={"position": 0})
        check("清掉最后一位后整个场景无手动排序",
              status == 200 and all(s["manual_rank"] is None for s in scene_r4["scripts"]))
        check("清排序不丢话术", status == 200 and len(scene_r4["scripts"]) == len(scene_r3["scripts"]))

    status, _ = call("POST", f"/api/live/scenes/{opening['id']}/entry-mode",
                     token=student, payload={"mode": "silent"})
    check("进场模式还原为 silent", status == 200)

    # ---------------------------------------------------------------- 权限
    section("权限")
    status, _ = call("POST", f"/api/live/scenes/{opening['id']}/pin", token=student)
    check("学员不能置顶 403", status == 403, f"实际 {status}")
    status, _ = call(
        "POST",
        f"/api/live/scenes/{opening['id']}/scripts",
        payload={"scene_id": opening["id"], "text": "匿名不该能建话术"},
    )
    check("匿名新增话术 401", status == 401, f"实际 {status}")
    status, _ = call("POST", "/api/live/scenes", token=student, payload={"name": "学员建的场景"})
    check("学员不能建场景 403（库结构仍归讲师）", status == 403, f"实际 {status}")

    # ------------------------------------------------------------ 编码冲突
    section("编码冲突与编辑")
    status, _ = call(
        "POST",
        f"/api/live/scenes/{opening['id']}/scripts",
        token=teacher,
        payload={"scene_id": opening["id"], "text": "重复快捷码应当被拒绝", "code": "aa1"},
    )
    check("重复快捷码被拒 409", status == 409, f"实际 {status}")
    status, updated = call(
        "PUT",
        f"/api/live/scripts/{CREATED_SCRIPT_ID}",
        token=teacher,
        payload={"text": "改过之后的临时话术文本"},
    )
    check("讲师可编辑话术", status == 200 and updated["text"] == "改过之后的临时话术文本", f"{status}")
    status, auto = call(
        "POST",
        f"/api/live/scenes/{opening['id']}/scripts",
        token=teacher,
        payload={"scene_id": opening["id"], "text": "留空 code 时自动编号", "code": ""},
    )
    check("留空 code 自动生成", status == 201 and bool(auto.get("code")), f"{status} {auto.get('code') if isinstance(auto, dict) else auto}")
    if status == 201:
        call("DELETE", f"/api/live/scripts/{auto['id']}", token=teacher)

    status, _ = call("GET", "/api/live/scenes/does-not-exist", token=student)
    check("不存在的场景返回 404", status == 404, f"实际 {status}")

    # ------------------------------------------------------- 录音清单一致性
    section("录音清单一致性")
    # 中途新建过临时话术，这里必须取**当前**的面板总数，不能复用一开始那份
    status, fresh = call("GET", "/api/live/bootstrap", token=student)
    check("重新拉取面板仍是 200", status == 200, f"实际 {status}")
    status, index = call("GET", "/api/live/audio-index", token=student)
    check("audio-index 返回 200", status == 200, f"实际 {status}")
    if status == 200:
        check("脚本总数与面板一致", index["scripts"] == fresh["script_total"], f"{index['scripts']} vs {fresh['script_total']}")
        check(
            "已录 + 待录 = 总数",
            index["recorded"] + index["pending_recording"] == index["scripts"],
            f"{index['recorded']} + {index['pending_recording']} vs {index['scripts']}",
        )
        check("任务清单条目数与待录数一致", len(index["items"]) == index["pending_recording"] or index["pending_recording"] > 200)
        check("清单里不含已有录音的条目", all(i["reason"] in ("missing", "override") for i in index["items"]))

    cleanup()

    print(f"\n结果：{len(PASSED)} 项通过，{len(FAILED)} 项失败")
    if FAILED:
        print("失败项：")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
