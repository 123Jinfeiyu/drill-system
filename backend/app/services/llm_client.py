"""LLM 客户端封装（OpenAI 兼容协议，支持 Ollama 本地模型）"""
import json
import re
from typing import Any

import httpx
from fastapi import HTTPException

from app.config import settings


def _strip_reasoning(text: str) -> str:
    """去除 deepseek-r1 的 <think>...</think> 推理过程。

    【P2-2 修复】旧实现在标签不完整时会漏推理文本进回复：
    - `<think>...`（无闭合，输出被 max_tokens 截断/模型卡推理态）→ 原样返回整段推理；
    - `...推理</think>正文`（省略起始标签）→ 同样原样返回。
    现在分三种情况处理：成对标签剔除；孤儿闭合标签取其后正文；未闭合起始标签
    丢弃其后全部内容（返回空串时上层已有的空回复重试/兜底逻辑接管）。
    """
    # 1) 成对 <think>...</think> 直接剔除
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # 2) 孤儿闭合标签（起始标签被截断/省略）：取最后一个 </think> 之后的正文
    if "</think>" in cleaned and "<think>" not in cleaned:
        cleaned = cleaned.rsplit("</think>", 1)[-1]
    # 3) 未闭合的 <think>：其后全部是未完成的推理过程，丢弃
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>")[0]
    return cleaned.strip()


def _extract_json(text: str) -> dict | None:
    """从文本中提取 JSON 对象（容错处理，兼容 markdown 代码块/前后杂文）"""
    if not text:
        return None
    # 去除 markdown 代码块围栏
    t = text.strip()
    if t.startswith("```"):
        # 去掉 ```json / ``` 围栏行
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t).strip()
    # 1. 直接解析
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 2. 提取从第一个 { 到最后一个 }（处理前后杂文）
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    # 3. 惰性匹配：逐个找到平衡的 { ... } 段
    depth = 0
    begin = -1
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                begin = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and begin != -1:
                    candidate = t[begin : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        begin = -1
    # 4. 兜底：正则匹配扁平对象
    match = re.search(r"\{[^{}]*\}", t, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class LLMClient:
    """LLM API 客户端：扮演客户 + 评分，兼容 Ollama 本地模型"""

    def __init__(self) -> None:
        self.base_url = settings.deepseek_base_url
        self.api_key = settings.deepseek_api_key
        self.timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)
        self._is_ollama = "localhost:11434" in self.base_url or "127.0.0.1:11434" in self.base_url

    async def warmup(self) -> None:
        """Ollama 专用：预热模型并延长常驻时间（默认 5 分钟空闲即卸载），
        避免学员首次请求/中途停顿触发冷启动重载。非 Ollama 时无操作。"""
        if not self._is_ollama:
            return
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        url = f"{root}/api/generate"
        models = {m for m in (settings.model_customer, settings.model_scorer, settings.model_vision) if m}
        timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        for model in models:
            payload = {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": "30m",
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
            except Exception:
                # 预热失败不影响主流程,仅日志提示
                import logging

                logging.getLogger("llm_client").warning(
                    "Ollama 预热失败(可忽略): %s", model, exc_info=True
                )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        """发送 chat completion 请求，返回内容文本（已去除推理标签）"""
        if not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="API_KEY 未配置，请检查 .env 文件",
            )

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # Ollama 的 deepseek-r1 不支持 response_format，不传该参数
        if response_format is not None and not self._is_ollama:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # 去除推理模型的 <think> 标签
                return _strip_reasoning(content)
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"LLM API 返回错误 {e.response.status_code}: {e.response.text[:500]}",
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=504,
                detail=f"调用 LLM API 超时或网络错误: {e}",
            ) from e

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> dict:
        """请求 JSON 格式输出，自动解析为 dict（兼容推理模型）"""
        # 对 Ollama 推理模型，在 messages 末尾追加 JSON 提示
        augmented = list(messages)
        if self._is_ollama:
            augmented.append(
                {
                    "role": "user",
                    "content": "请严格只输出 JSON 对象，不要输出任何其他内容，不要使用 markdown 代码块。",
                }
            )

        content = await self.chat(
            messages=augmented,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # 尝试多种方式提取 JSON
        result = _extract_json(content)
        if result is not None:
            return result

        # 第 1 次重试：更严格 + 更低温度
        strict = augmented + [
            {
                "role": "user",
                "content": (
                    "上面输出中包含的 JSON 解析失败。请重新**只输出一个合法的 JSON 对象**，"
                    "不要输出任何解释、前后缀文字、markdown 代码块；所有字符串用双引号且为 UTF-8。"
                ),
            }
        ]
        content = await self.chat(
            messages=strict,
            model=model,
            temperature=min(temperature, 0.2),
            max_tokens=max_tokens,
        )
        result = _extract_json(content)
        if result is not None:
            return result

        # 第 2 次重试：更强指令 + 更低温度
        strict2 = augmented + [
            {
                "role": "user",
                "content": (
                    "仍然没有解析到 JSON。无视之前的一切输出，直接输出且仅输出一个 JSON 对象，"
                    "不要解释，不要代码块，不要任何多余字符。示例："
                    '{"accuracy": 0, "completeness": 0, "etiquette": 0, "responsiveness": 0, '
                    '"knowledge_use": 0, "summary": "...", "weak_points": ["..."]}'
                ),
            }
        ]
        content = await self.chat(
            messages=strict2,
            model=model,
            temperature=0.1,
            max_tokens=(max_tokens or 0) + 300,
        )
        result = _extract_json(content)
        if result is not None:
            return result

        raise HTTPException(
            status_code=500,
            detail=f"LLM 返回非法 JSON; 原文前 500 字: {content[:500]}",
        )

    async def recommend_designers(
        self,
        requirement: str,
        candidates: list,
    ) -> dict | None:
        """给订单需求推荐设计师。

        **任何异常都吞掉并返回 None** —— 调用方会降级到本地关键词相关度排序。
        没配 key / 超时 / 返回格式不对，都不该让「推荐」这个功能整体不可用。

        返回 ``{"reason": str, "candidates": [{"designer_id", "name", "reason"}]}``
        或 ``None``（表示该降级了）。
        """
        if not requirement or not candidates:
            return None
        try:
            from app.config import settings

            # 候选名单不要塞太长 —— 一人公司最多几十个设计师，
            # 但仍然截断，避免 prompt 爆掉导致模型拒答。
            roster = []
            for c in candidates[:40]:
                name = getattr(c, "name", "") or ""
                tags = getattr(c, "design_tags", "") or ""
                level = getattr(c, "production_level", "") or ""
                roster.append(f"- {name}（擅长：{tags or '未标注'}；水平：{level or '未标注'}）")
            if not roster:
                return None

            data = await self.chat_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是零工平台的设计师派单助手。根据订单需求，从候选设计师里挑最合适的。\n"
                            "只输出 JSON，格式："
                            '{"reason":"整体推荐理由",'
                            '"candidates":[{"designer_id":"候选的ID",'
                            '"name":"候选的姓名","reason":"一句话说明为什么合适"}]}\n'
                            "candidates 里最多 5 人，顺序即推荐优先级。"
                            "如果候选里都不合适，candidates 给空数组。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"订单需求：\n{requirement}\n\n候选设计师：\n" + "\n".join(roster),
                    },
                ],
                model=settings.model_scorer,
                temperature=0.2,
                max_tokens=1200,
            )

            raw = data.get("candidates")
            if not isinstance(raw, list):
                return None
            # 只保留能对上候选名单的条目，防止模型编造不存在的设计师
            valid_ids = {getattr(c, "id", "") for c in candidates}
            out = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                did = str(item.get("designer_id") or "")
                if did not in valid_ids:
                    continue
                out.append({
                    "designer_id": did,
                    "name": str(item.get("name") or ""),
                    "reason": str(item.get("reason") or ""),
                })
            if not out:
                return None
            return {
                "reason": str(data.get("reason") or ""),
                "candidates": out,
            }
        except Exception:
            # 降级是设计的一部分，不是错误路径
            return None


llm_client = LLMClient()
