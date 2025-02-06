from .base_client import BaseClient
import asyncio
from typing import AsyncGenerator, List, Tuple
import aiohttp
import json
from app.utils.logger import logger


class CommonClient(BaseClient):
    def __init__(self, api_key: str, api_url: str):
        """初始化 GPT-4 客户端
        Args:
            api_key: API密钥
            api_url: GPT-4 API地址
        """
        super().__init__(api_key, api_url)

    async def stream_chat(
        self, messages: List[dict], model: str = "gpt-4o"
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """实现流式对话
        Args:
            messages: 消息列表
            model: 模型名称，默认为 "gpt-4o"
        Yields:
            tuple[str, str]: 内容类型和内容
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": messages,
            "max_tokens": 8192,
            "stream": True,
        }

        async for chunk in self._make_request(headers, data):
            try:
                chunk_data = chunk.decode("utf-8").strip().splitlines()
                if not chunk_data:
                    continue
                for line in chunk_data:
                    if not line:
                        continue
                    if line.startswith("data: "):
                        line = line[6:].strip()
                    if line == "[DONE]":
                        return
                    try:
                        response_json = json.loads(line)
                        for choice in response_json.get("choices", []):
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                if model == "deepseek-r1":
                                    yield ("thinking", content)
                                    if "</think>" in content:
                                        return
                                else:
                                    yield ("content", content)
                    except json.JSONDecodeError as e:
                        logger.error(f"解析流式响应时发生错误: {e}")
            except Exception as e:
                logger.error(f"处理流式响应时发生错误: {e}")
