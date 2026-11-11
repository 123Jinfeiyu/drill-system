# -*- coding: utf-8 -*-
"""把《客服话术总库.xlsx》导入实战话术面板。

用法（必须在 backend 目录下执行，drill.db 与 .env 都是相对路径）::

    .\\.venv\\Scripts\\python.exe -X utf8 seed_live_scripts.py --dry-run   # 先看计划
    .\\.venv\\Scripts\\python.exe -X utf8 seed_live_scripts.py             # 正式导入

导入范围（有意取舍）::

    一线话术快捷码库    84 条 / 29 场景  source=quick     ← 主面板，保留原有快捷码
    会员话术库          22 条 /  8 场景  source=business
    利率资方话术库      29 条 / 10 场景  source=business
    逾期催收话术库      24 条 /  9 场景  source=business
    常见问题话术        25 条 /  1 场景  source=faq
    -------------------------------------------------------------
    「客服话术库」**不导入**：它的正文与快捷码库 hk1~hk5、ww1~ww5 等逐字重复，
    导进来只会让坐席在搜索结果里看到同一句话出现两次。

编码规则（``LiveScript.code`` 同时就是录音文件名）::

    快捷码库   → 沿用 Excel 里的原始快捷码（aa1 / hy2 / ww5），坐席已经熟悉它
    业务话术库 → <场景码>-<序>，如 b10-03
    常见问题   → faq01-07

幂等：按 code 做 upsert，可反复重跑。重跑时**保护人工状态**——``pinned``（置顶）、
``use_count``（使用次数）、``audio_file``（录音文件名覆盖项）都不覆盖，
只有素材本身（正文、标题、顺序、自动播报）以 Excel 为准。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl
from sqlalchemy import select

from app.database import AsyncSessionLocal, init_db
from app.models import LiveScene, LiveScript

XLSX = Path(__file__).resolve().parent / "客服话术总库.xlsx"

SHEET_QUICK = "一线话术快捷码库"
SHEET_FAQ = "常见问题话术"
BUSINESS_SHEETS: tuple[str, ...] = ("会员话术库", "利率资方话术库", "逾期催收话术库")
FAQ_SCENE_NAME = "常见问题速查"

# 话务动线阶段：只给快捷码库人工指定（业务话术库统一归 business）
PHASE_BY_SCENE: dict[str, str] = {
    "开场": "opening",
    "安抚": "support",
    "稍等": "support",
    "工号": "support",
    "合作平台电话": "support",
    "常用资金方": "support",
    "常用语": "support",
    "麻烦礼貌用语": "support",
    "咨询处理时间": "support",
    "统一安抚话术": "support",
    "升级反馈": "support",
    "结束语": "closing",
    "友好关闭会话": "closing",
}
DEFAULT_PHASE = "business"

# 明显不是话术的占位行（链接失效、无效说明），导入时跳过
# 长度阈值放到 4：「客户id：」这类短模板虽然不能播报，但坐席要一键复制，不能丢
_JUNK = re.compile(r"^[（(][^)）]*(失效|已无|无|作废)[^)）]*[)）]$")
MIN_TEXT_LEN = 4


class Item:
    """一条待导入话术。``code`` 留空表示要按场景自动生成。"""

    __slots__ = ("scene_name", "label", "text", "code", "sort_order")

    def __init__(self, scene_name: str, label: str, text: str, code: str = "") -> None:
        self.scene_name = scene_name
        self.label = label
        self.text = text
        self.code = code
        self.sort_order = 0


class SceneSpec:
    __slots__ = ("code", "name", "phase", "source", "sort_order")

    def __init__(self, code: str, name: str, phase: str, source: str, sort_order: int) -> None:
        self.code = code
        self.name = name
        self.phase = phase
        self.source = source
        self.sort_order = sort_order


def _clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_junk(text: str) -> bool:
    return len(text) < MIN_TEXT_LEN or bool(_JUNK.match(text))


def read_quick(wb) -> tuple[list[str], list[Item], list[str]]:
    """一线话术快捷码库：场景 | 话术 | 快捷代码。快捷码原样保留（坐席已熟悉）。"""
    order: list[str] = []
    items: list[Item] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for row in wb[SHEET_QUICK].iter_rows(min_row=2, values_only=True):
        if not row or row[1] is None:
            continue
        scene = _clean(row[1])
        text = _clean(row[2])
        code = _clean(row[3]) if len(row) > 3 else ""
        if not scene or not text:
            continue
        if scene not in order:
            order.append(scene)
        if not code:
            skipped.append(f"{scene} · {text[:20]}（缺快捷码）")
            continue
        if code in seen:
            skipped.append(f"{scene} · 快捷码重复 {code}")
            continue
        if _is_junk(text):
            skipped.append(f"{scene} · {code}（占位行）")
            continue
        seen.add(code)
        items.append(Item(scene, "", text, code))
    return order, items, skipped


def read_business(wb, sheet: str) -> tuple[list[str], list[Item]]:
    """业务话术库：一级分类 | 问题场景 | 话术内容。scene=一级分类，label=问题场景。"""
    order: list[str] = []
    items: list[Item] = []
    for row in wb[sheet].iter_rows(min_row=2, values_only=True):
        if not row or row[1] is None:
            continue
        scene = _clean(row[1])
        label = _clean(row[2])
        text = _clean(row[3]) if len(row) > 3 else ""
        if not scene or not text or _is_junk(text):
            continue
        if scene not in order:
            order.append(scene)
        items.append(Item(scene, label, text))
    return order, items


def read_faq(wb) -> list[Item]:
    """常见问题话术：常见问题 | 参考话术。统一收进一个速查场景。"""
    items: list[Item] = []
    for row in wb[SHEET_FAQ].iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        label = _clean(row[0])
        text = _clean(row[1]) if len(row) > 1 else ""
        if not text or _is_junk(text):
            continue
        items.append(Item(FAQ_SCENE_NAME, label, text))
    return items


def build_plan() -> tuple[list[SceneSpec], list[Item], dict[str, list[str]]]:
    """读五张表 → 场景 + 话术两层结构，保持 Excel 原有顺序。

    分两趟：先把场景和条目收集齐，再统一发号。这样「场景内编码」一定不会撞车
    ——第一版按表级前缀发号，同一张表里两个场景会拿到同一个前缀。
    """
    if not XLSX.is_file():
        raise SystemExit(f"找不到话术总库：{XLSX}")
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)

    scenes: list[SceneSpec] = []
    items: list[Item] = []
    trouble: dict[str, list[str]] = {}

    # 1) 快捷码库排最前——它是实战主面板
    order, quick_items, skipped = read_quick(wb)
    if skipped:
        trouble["快捷码库跳过"] = skipped
    for name in order:
        scenes.append(
            SceneSpec(f"q{len(scenes) + 1:02d}", name, PHASE_BY_SCENE.get(name, DEFAULT_PHASE), "quick", len(scenes))
        )
    items.extend(quick_items)

    # 2) 三张业务话术库
    for sheet in BUSINESS_SHEETS:
        order, biz_items = read_business(wb, sheet)
        for name in order:
            scenes.append(SceneSpec(f"b{len(scenes) + 1:02d}", name, DEFAULT_PHASE, "business", len(scenes)))
        items.extend(biz_items)

    # 3) 常见问题速查
    faq_items = read_faq(wb)
    if faq_items:
        scenes.append(SceneSpec(f"faq{len(scenes) + 1:02d}", FAQ_SCENE_NAME, DEFAULT_PHASE, "faq", len(scenes)))
        items.extend(faq_items)

    # ---- 统一发号：场景内顺序 + 条目编码 ----
    code_by_scene = {scene.name: scene.code for scene in scenes}
    counters: Counter[str] = Counter()
    for item in items:
        index = counters[item.scene_name]
        counters[item.scene_name] += 1
        item.sort_order = index
        if not item.code:
            item.code = f"{code_by_scene[item.scene_name]}-{index + 1:02d}"

    duplicates = [code for code, n in Counter(i.code for i in items).items() if n > 1]
    if duplicates:
        raise SystemExit(f"编码冲突，导入中止（会覆盖错误的话术）：{duplicates}")

    return scenes, items, trouble


async def apply_plan(scenes: list[SceneSpec], items: list[Item], *, dry_run: bool) -> dict:
    # dry-run 也要建表：要报出「会新建几条 / 会更新几条」就必须能读现有数据。
    # create_all 只补缺失的表，不会动既有数据。
    await init_db()
    scene_by_name: dict[str, LiveScene] = {}
    counters = Counter()

    async with AsyncSessionLocal() as db:
        for spec in scenes:
            existing = (
                await db.execute(select(LiveScene).where(LiveScene.code == spec.code))
            ).scalar_one_or_none()
            if existing is None:
                # 同名场景已被人工建过 → 复用，避免长出两个同名面板
                existing = (
                    await db.execute(select(LiveScene).where(LiveScene.name == spec.name))
                ).scalar_one_or_none()
            if existing is None:
                scene = LiveScene(
                    code=spec.code,
                    name=spec.name,
                    phase=spec.phase,
                    source=spec.source,
                    sort_order=spec.sort_order,
                )
                if not dry_run:
                    db.add(scene)
                counters["scenes_created"] += 1
            else:
                # 素材以 Excel 为准；pinned 是人的决定，不动
                existing.name = spec.name
                existing.phase = spec.phase
                existing.source = spec.source
                existing.sort_order = spec.sort_order
                scene = existing
                counters["scenes_updated"] += 1
            scene_by_name[spec.name] = scene
        if not dry_run:
            await db.flush()

        for item in items:
            scene = scene_by_name[item.scene_name]
            existing = (
                await db.execute(select(LiveScript).where(LiveScript.code == item.code))
            ).scalar_one_or_none()
            is_first = item.sort_order == 0
            if existing is None:
                if not dry_run:
                    db.add(
                        LiveScript(
                            scene_id=scene.id,
                            code=item.code,
                            label=item.label,
                            text=item.text,
                            auto_play=is_first,
                            sort_order=item.sort_order,
                        )
                    )
                counters["scripts_created"] += 1
            else:
                # 素材字段刷新；use_count / audio_file 是使用中产生的状态，必须保住
                existing.label = item.label
                existing.text = item.text
                existing.auto_play = is_first
                existing.sort_order = item.sort_order
                if not dry_run:
                    existing.scene_id = scene.id
                counters["scripts_updated"] += 1
        if not dry_run:
            await db.commit()

    return dict(counters)


def main() -> int:
    parser = argparse.ArgumentParser(description="导入实战话术到面板")
    parser.add_argument("--dry-run", action="store_true", help="只解析并打印计划，不写库")
    args = parser.parse_args()

    if not (Path.cwd() / "drill.db").exists():
        print(f"提示：当前目录 {Path.cwd()} 下没有 drill.db，请确认在 backend 目录下执行")

    scenes, items, trouble = build_plan()
    print(f"解析完成：{len(scenes)} 个场景 / {len(items)} 条话术")
    for key, rows in trouble.items():
        print(f"  {key} {len(rows)} 条：")
        for row in rows[:10]:
            print(f"    - {row}")

    print("  阶段分布:", dict(Counter(s.phase for s in scenes)))
    print("  来源分布:", dict(Counter(s.source for s in scenes)))
    print("  前 3 个场景预览：")
    for spec in scenes[:3]:
        rows = [i for i in items if i.scene_name == spec.name]
        codes = "、".join(i.code for i in rows[:5])
        print(f"    [{spec.phase}] {spec.name}（{len(rows)} 条）: {codes}")

    result = asyncio.run(apply_plan(scenes, items, dry_run=args.dry_run))
    label = "（dry-run，未写库）" if args.dry_run else ""
    print(
        f"导入完成{label}："
        f"场景 新建 {result.get('scenes_created', 0)} / 更新 {result.get('scenes_updated', 0)}；"
        f"话术 新建 {result.get('scripts_created', 0)} / 更新 {result.get('scripts_updated', 0)}"
    )
    print("下一步：把录音按 <快捷码>.mp3 放进 backend/audio/live/，刷新页面即生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
