import os
from dotenv import load_dotenv
import aiohttp
import asyncio

# 加载环境变量
load_dotenv()

from fastapi import FastAPI, Depends, Request
from fastapi.responses import StreamingResponse
from app.utils.logger import logger
from app.utils.auth import verify_api_key
from app.deepclaude.deepclaude import DeepClaude
import os

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="DeepClaude API")
# 允许所有源、方法和头
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 或按需指定域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_API_KEY = os.getenv("BASE_API_KEY")
BASE_API_URL = os.getenv("BASE_API_URL")

# 验证日志级别
logger.debug("当前日志级别为 DEBUG")
logger.info("开始请求")


async def forward_stream(request: Request, target_url: str, headers: dict):
    """透传请求并从目标API获取流式响应"""
    # 获取请求体
    body = await request.body()

    try:
        # 发送请求到目标服务，获取流式响应
        async with aiohttp.ClientSession() as session:
            async with session.post(target_url, headers=headers, data=body) as response:
                # 检查响应状态
                if response.status != 200:
                    raise Exception(f"Error response from API: {response.status}")

                # 按块读取响应数据
                async for chunk in response.content.iter_any():
                    # 将目标服务返回的每块数据发送给客户端
                    yield chunk

    except asyncio.CancelledError:
        # 客户端主动断开连接，记录并继续发送剩余数据
        print("Client disconnected (CancelledError). Continuing to send data.")
    except Exception as e:
        # 处理其他异常
        print(f"Error while forwarding stream: {e}")
        raise


@app.get("/", dependencies=[Depends(verify_api_key)])
async def root():
    logger.info("访问了根路径")
    return {"message": "Welcome to DeepClaude API"}


@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(request: Request):
    """处理聊天完成请求，返回流式响应

    请求体格式应与 OpenAI API 保持一致，包含：
    - messages: 消息列表
    - model: 模型名称（可选）
    - stream: 是否使用流式输出（必须为 True）
    """

    try:
        # 1. 获取并验证请求数据
        body = await request.json()
        messages = body.get("messages")
        if not messages:
            return {"error": "messages 不能为空"}

        if not body.get("stream", False):
            return {"error": "目前仅支持流式输出，stream 必须为 True"}

        # 2. 验证model
        model = body.get("model", "deepclaude")
        if model == "deepclaude":
            chat_service = DeepClaude(BASE_API_KEY, BASE_API_URL)

            # 4. 返回流式响应
            return StreamingResponse(
                chat_service.generate_chunks(messages=messages),
                media_type="text/event-stream",
            )

        else:
            # 透传
            headers = {
                "Authorization": f"Bearer {BASE_API_KEY}",
                "Content-Type": "application/json",
            }
            return StreamingResponse(
                forward_stream(request, BASE_API_URL, headers),
                media_type="text/event-stream",
            )

    except Exception as e:
        logger.error(f"处理请求时发生错误: {e}")
        return {"error": str(e)}
