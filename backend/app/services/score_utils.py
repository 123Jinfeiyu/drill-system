"""评分结果容错提取工具（剧本演练评分 / Q&A 演练场评分共用）。

【P2-1 修复】scorer.py 与 practice_agent.py 原先各有一份完全相同的
_clamp / _coerce_number / _extract_score / _pick 与中英文别名表（practice 侧
还缺嵌套/wrapper 容错），统一收敛到这里，取 scorer 的完整容错实现。
"""
import re
from typing import Any

# 各评分维度的 key 别名（英文 + 中文），用于容错提取
SCORE_ALIASES: dict[str, list[str]] = {
    "accuracy": ["accuracy", "准确性", "准确度", "准确"],
    "completeness": ["completeness", "完整度", "完整性", "完整"],
    "etiquette": ["etiquette", "话术规范", "礼仪", "话术", "服务礼仪"],
    "responsiveness": ["responsiveness", "响应速度", "响应性", "响应", "反应速度"],
    "knowledge_use": ["knowledge_use", "知识运用", "知识使用", "知识应用"],
}

# summary / weak_points 的中文别名
SUMMARY_ALIASES = ["summary", "总结", "整体评价", "评价", "评语", "总评", "点评"]
WEAK_ALIASES = [
    "weak_points",
    "薄弱点",
    "薄弱",
    "不足",
    "不足之处",
    "改进点",
    "缺点",
    "问题",
]
# 演练场评分特有的字段别名
SUGGESTION_ALIASES = ["suggestions", "建议", "改进建议", "suggestion"]
BUSINESS_ALIASES = ["business_summary", "业务小结", "小结", "工作记录", "工单"]

# 可能包裹整体结果的 wrapper key
_WRAPPER_KEYS = (
    "result",
    "data",
    "scores",
    "score",
    "评分",
    "评分结果",
    "score_result",
)

# 数值型维度可能嵌套的子对象 key
_NEST_KEYS = ("scores", "score", "评分", "维度评分", "dimensions", "details")

# dict 型分值的子字段
_DICT_SCORE_SUBKEYS = (
    "score",
    "分数",
    "得分",
    "评分",
    "分",
    "total",
    "value",
    "rating",
)


def clamp(value: Any, lo: int = 0, hi: int = 100) -> float:
    """数值范围校验，防止 LLM 越界污染成绩"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return float(max(lo, min(hi, v)))


def coerce_number(value: Any) -> float:
    """从单个值中提取数值（不做范围限制）。
    支持 int/float、{"score": 85} 型 dict、"85分"/"85" 型字符串。
    """
    if isinstance(value, bool):  # bool 是 int 子类，需排除
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for sub in _DICT_SCORE_SUBKEYS:
            if sub in value:
                return coerce_number(value[sub])
        for v in value.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return 0.0
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value)
        return float(m.group(0)) if m else 0.0
    return 0.0


def unwrap(raw: dict) -> dict:
    """若整体被包了一层 wrapper 且内层才含期望字段，剥到内层。"""
    expected = set(SCORE_ALIASES) | set(SUMMARY_ALIASES) | set(WEAK_ALIASES)
    if any(k in raw for k in expected):
        return raw
    for wrap_key in _WRAPPER_KEYS:
        inner = raw.get(wrap_key)
        if isinstance(inner, dict):
            return inner
    return raw


def extract_score(raw: dict, field: str) -> float:
    """容错提取某维度分数：英文/中文 key、嵌套 scores 子对象、dict/str/num 值。"""
    containers = [raw]
    for nest_key in _NEST_KEYS:
        nested = raw.get(nest_key)
        if isinstance(nested, dict):
            containers.append(nested)
    for alias in SCORE_ALIASES[field]:
        for c in containers:
            if alias in c:
                return clamp(coerce_number(c[alias]))
    return 0.0


def pick(raw: dict, keys: list[str], default: Any = None) -> Any:
    """按别名顺序取首个存在的值。"""
    for k in keys:
        if k in raw:
            return raw[k]
    return default
