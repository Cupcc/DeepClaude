import time
import json
from typing import AsyncGenerator, Optional, List, Dict, Tuple
from app.utils.logger import logger
from app.clients.common_client import CommonClient


class DeepClaude:
    """处理 DeepSeek 和 Claude API 的流式输出衔接"""

    def __init__(
        self,
        api_key: str,
        api_url: str,
        thinking_model: str = "deepseek-r1",
        final_model: str = "claude-3-5-sonnet-latest",
    ):
        """
        :param api_key: 用于调用后端 API 的密钥
        :param api_url: 后端 API 的 URL
        :param thinking_model: 思考模型名称，默认 "deepseek-r1"
        :param final_model: 最终回答模型名称，默认 "claude-3-5-sonnet-latest"
        """
        self.client = CommonClient(api_key, api_url)
        self.thinking_model = thinking_model
        self.final_model = final_model
        self.model_name = "deepclaude"

    def _initialize_chunk(self, chunk_id: str, created: int = None) -> Dict:
        """
        生成并初始化一个基础的 SSE chunk 结构。
        :param chunk_id: chunk 的 id
        :param model: chunk 中的 model 字段
        :param created: 可选，如果不传则使用当前时间戳
        :return: 一个 chunk 的 dict 结构
        """
        if created is None:
            created = int(time.time())
        return {
            "choices": [
                {
                    "delta": {"content": ""},  # 初始为空
                    "finish_reason": None,
                    "index": 0,
                }
            ],
            "id": chunk_id,
            "model": self.model_name,
            "object": "chat.completion.chunk",
            "created": created,
        }

    def _set_chunk_content(self, chunk: Dict, content: str) -> None:
        """
        修改 chunk 中的 content。
        :param chunk: chunk 结构
        :param content: 要替换进去的文本
        """
        chunk["choices"][0]["delta"]["content"] = content

    def _initialize_start_message(self) -> Dict:
        """
        初始化开始消息格式。
        """
        return {
            "choices": [
                {
                    "delta": {"content": "", "role": "assistant"},
                    "finish_reason": None,
                    "index": 0,
                }
            ],
            "created": int(time.time()),
            "id": "chatcmpl-start-message-id",
            "model": self.model_name,
            "object": "chat.completion.chunk",
        }

    def _initialize_end_message(self) -> Dict:
        """
        初始化结束消息格式。
        """
        return {
            "choices": [{"delta": {}, "finish_reason": "stop", "index": 0}],
            "created": int(time.time()),
            "id": "chatcmpl-end-message-id",
            "model": self.model_name,
            "object": "chat.completion.chunk",
        }

    async def generate_chunks(self, messages: List) -> AsyncGenerator[bytes, None]:
        """
        先调用 thinking_model 获取思考过程，再调用 final_model 获取正式回答。
        将每一段响应封装为 SSE chunk 格式（bytes）并 yield 出去。
        """
        thinking_content: str = ""

        # ============== 第一段：发送开始消息 ==============
        start_message = self._initialize_start_message()
        sse_start = f"data: {json.dumps(start_message, ensure_ascii=False)}\n\n"
        yield sse_start.encode("utf-8")

        # 生成 chunk
        chunk = self._initialize_chunk(
            chunk_id=f"chatcmpl-{hex(int(time.time() * 1000))[2:]}"
        )
        # ============== 第一段：思考模型调用 ==============
        async for content_type, content in self.client.stream_chat(
            messages, self.thinking_model
        ):
            if content_type == "thinking":
                # 累积思考内容
                thinking_content += content

            # 设置内容
            self._set_chunk_content(chunk, content)

            # 转为 SSE 格式并以 bytes 形式 yield
            # 注意 ensure_ascii=False 以支持中文、emoji 等
            sse_string = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield sse_string.encode("utf-8")

        # 思考结束后，把思考内容加到下一条消息
        messages.append(
            {
                "role": "assistant",
                "content": (
                    f"Here's my thinking process:\n\n{thinking_content}"
                    f"Based on the thinking process, I will now provide my response:"
                ),
            }
        )

        # 分隔线
        self._set_chunk_content(chunk, content="\n\n")
        sse_string = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield sse_string.encode("utf-8")

        # ============== 第二段：正式回答模型调用 ==============
        async for content_type, content in self.client.stream_chat(
            messages, self.final_model
        ):

            self._set_chunk_content(chunk, content)

            sse_string = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield sse_string.encode("utf-8")

        # ============== 发送结束消息 ==============
        end_message = self._initialize_end_message()
        sse_end = f"data: {json.dumps(end_message, ensure_ascii=False)}\n\n"
        yield sse_end.encode("utf-8")

        logger.info("Chatting done.")
        # 所有输出完成后，发送 [DONE] 标识，结束 SSE
        yield b"data: [DONE]\n\n"
