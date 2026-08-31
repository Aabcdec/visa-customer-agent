"""签证客服智能体 - FastAPI 服务入口（去 Coze 化，DeepSeek 直连）。

端点：
- POST /run                     同步运行整张图
- POST /stream_run              SSE 流式运行
- POST /async_run               异步任务提交（内存存储）
- GET  /task/{task_id}          查询异步任务
- POST /node_run/{node_id}      单节点运行
- POST /cancel/{run_id}         取消运行
- POST /v1/chat/completions     OpenAI 兼容接口
- GET  /health                  健康检查
- GET  /graph_parameter         图的输入输出 schema
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from utils.context import Context, new_context
from graphs.graph import main_graph

# Langfuse 追踪（密钥用环境变量 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL）
try:
    from langfuse import get_client as _langfuse_get_client
    from langfuse import observe as _langfuse_observe
except ImportError:  # 未安装 langfuse 时仍可本地跑通，不阻断 /run
    _langfuse_get_client = None
    _langfuse_observe = lambda **_kw: (lambda f: f)  # noqa: E731

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 900  # 15分钟
HEADER_X_RUN_ID = "x-run-id"
HEADER_X_WORKFLOW_STREAM_MODE = "x-workflow-stream-mode"

# 运行中的任务表：run_id -> asyncio.Task
running_tasks: Dict[str, asyncio.Task] = {}

# 异步任务存储（内存版，重启即失）：task_id -> 状态
async_tasks: Dict[str, Dict[str, Any]] = {}
# 防止 uvicorn reload 时双进程竞争
_ASYNC_TASKS_LOCK = asyncio.Lock()


def _resolve_ctx(method: str, request: Request) -> Context:
    """从请求构造运行上下文；支持上游 x-run-id 透传。"""
    headers = {k: v for k, v in request.headers.items()}
    upstream_run_id = headers.get(HEADER_X_RUN_ID)
    ctx = new_context(method=method, headers=headers)
    if upstream_run_id:
        ctx.run_id = upstream_run_id
    return ctx


def _run_config(ctx: Context) -> RunnableConfig:
    """构造 LangGraph 运行配置：thread_id 与 run_id 对齐，便于 cancel 精确匹配。"""
    config: RunnableConfig = {"configurable": {"thread_id": ctx.run_id}}
    config.setdefault("metadata", {})["run_id"] = ctx.run_id
    return config


def _sse_event(data: Any, event_id: Any = None) -> str:
    id_line = f"id: {event_id}\n" if event_id else ""
    return f"{id_line}event: message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _find_node_func(node_id: str):
    """在编译图中按节点 id 查找节点函数、输入输出 schema 与 metadata。"""
    graph = main_graph.get_graph()
    node = graph.nodes.get(node_id)
    if node is None or node.data is None:
        return None, None, None, None
    func = getattr(node.data, "func", None)
    if func is None:
        return None, None, None, None
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    input_cls = params[0].annotation if params else None
    output_cls = getattr(sig.return_annotation, "__origin__", None)
    if output_cls is not None and hasattr(output_cls, "__args__"):
        output_cls = output_cls.__args__[0]
    elif not isinstance(sig.return_annotation, type):
        output_cls = None
    metadata = dict(node.metadata or {})
    return func, input_cls, output_cls, metadata


async def _run_graph(payload: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """同步运行整张图。"""
    config = _run_config(ctx)
    try:
        result = await main_graph.ainvoke(payload, config=config, context=ctx)
    except asyncio.CancelledError:
        logger.info(f"Run {ctx.run_id} was cancelled")
        return {"status": "cancelled", "run_id": ctx.run_id, "message": "Execution was cancelled"}
    if not isinstance(result, dict):
        result = {"result": result}
    result["run_id"] = ctx.run_id
    return result


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 预热：确保图可编译、节点可加载
    _ = main_graph.get_graph()
    yield
    # 取消所有在途任务
    for task in running_tasks.values():
        if not task.done():
            task.cancel()
    running_tasks.clear()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}


@app.get("/graph_parameter")
async def http_graph_inout_parameter():
    try:
        input_schema = main_graph.get_input_schema()
        output_schema = main_graph.get_output_schema()
        return {
            "input_schema": input_schema.model_json_schema(),
            "output_schema": output_schema.model_json_schema(),
            "code": 0,
            "msg": "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run")
@_langfuse_observe(name="visa-customer-/run")
async def http_run(request: Request) -> Dict[str, Any]:
    ctx = _resolve_ctx("run", request)
    raw_body = await request.body()
    try:
        body_text = raw_body.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    logger.info(f"Received request for /run: run_id={ctx.run_id}, body={body_text}")

    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    task = asyncio.create_task(_run_graph(payload, ctx))
    running_tasks[ctx.run_id] = task

    try:
        result = await asyncio.wait_for(task, timeout=float(TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        logger.error(f"Run execution timeout after {TIMEOUT_SECONDS}s for run_id: {ctx.run_id}")
        task.cancel()
        try:
            result = await task
        except asyncio.CancelledError:
            return {
                "status": "timeout",
                "run_id": ctx.run_id,
                "message": f"Execution timeout: exceeded {TIMEOUT_SECONDS} seconds",
            }
    except Exception as e:
        logger.error(f"Unexpected error in http_run: {e}\n{traceback.format_exc()}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        running_tasks.pop(ctx.run_id, None)
        if _langfuse_get_client is not None:
            try:
                _langfuse_get_client().flush()
            except Exception:
                logger.debug("langfuse flush skipped", exc_info=True)

    return result


@app.post("/stream_run")
async def http_stream_run(request: Request):
    ctx = _resolve_ctx("stream_run", request)
    workflow_stream_mode = request.headers.get(HEADER_X_WORKFLOW_STREAM_MODE, "").lower()
    workflow_debug = workflow_stream_mode == "debug"
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    logger.info(f"Received request for /stream_run: run_id={ctx.run_id}")

    async def event_generator() -> AsyncGenerator[str, None]:
        config = _run_config(ctx)
        try:
            async for chunk in main_graph.astream(payload, config=config, context=ctx):
                if workflow_debug and isinstance(chunk, tuple):
                    event_id, data = chunk
                    yield _sse_event(data, event_id)
                else:
                    yield _sse_event(chunk)
        except asyncio.CancelledError:
            logger.info(f"Stream cancelled for run_id: {ctx.run_id}")
        except Exception as e:
            logger.error(f"Error in stream_run: {e}\n{traceback.format_exc()}", exc_info=True)
            yield _sse_event({"error": str(e)})
        finally:
            running_tasks.pop(ctx.run_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/async_run")
async def http_async_run(request: Request) -> dict:
    """提交异步任务：立即返回 task_id，后台执行，结果可经 /task/{task_id} 查询。"""
    ctx = _resolve_ctx("async_run", request)
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    task_id = ctx.run_id

    async def _background_exec() -> None:
        try:
            result = await _run_graph(payload, ctx)
            status = "completed"
            error = ""
        except asyncio.CancelledError:
            result, status, error = {}, "cancelled", "Execution was cancelled"
        except Exception as e:
            result, status, error = {}, "failed", str(e)
            logger.error(f"Async run {task_id} failed: {e}\n{traceback.format_exc()}", exc_info=True)
        async with _ASYNC_TASKS_LOCK:
            async_tasks[task_id] = {"status": status, "result": result, "error": error}

    async with _ASYNC_TASKS_LOCK:
        async_tasks[task_id] = {"status": "running", "result": {}, "error": ""}

    task = asyncio.create_task(_background_exec())
    running_tasks[task_id] = task
    return {
        "task_id": task_id,
        "run_id": task_id,
        "status": "running",
        "message": "Task submitted",
    }


@app.get("/task/{task_id}")
async def http_get_task(task_id: str) -> dict:
    async with _ASYNC_TASKS_LOCK:
        row = async_tasks.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": task_id, **row}


@app.post("/cancel/{run_id}")
async def http_cancel(run_id: str, request: Request):
    _ = _resolve_ctx("cancel", request)
    logger.info(f"Attempting to cancel run_id: {run_id}")
    task = running_tasks.get(run_id)
    if task is None or task.done():
        return {
            "status": "not_found",
            "run_id": run_id,
            "message": "No active task found with this run_id",
        }
    task.cancel()
    return {
        "status": "success",
        "run_id": run_id,
        "message": "Cancellation signal sent",
    }


@app.post("/node_run/{node_id}")
async def http_node_run(node_id: str, request: Request):
    ctx = _resolve_ctx("node_run", request)
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    func, input_cls, _, metadata = _find_node_func(node_id)
    if func is None or input_cls is None:
        raise HTTPException(status_code=404, detail=f"node_id '{node_id}' not found")

    # 构造单节点子图运行（保留 metadata，LLM 节点依赖 llm_cfg）
    builder = StateGraph(input_cls, input_schema=input_cls)
    builder.add_node("sn", func, metadata=metadata)
    builder.set_entry_point("sn")
    builder.add_edge("sn", END)
    single_graph = builder.compile()

    try:
        result = await single_graph.ainvoke(payload, config=_run_config(ctx))
    except Exception as e:
        logger.error(f"Error in node_run {node_id}: {e}\n{traceback.format_exc()}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return result


# ========== OpenAI 兼容接口 ==========
from utils.llm import LLMClient  # noqa: E402
from utils.llm_messages import build_chat_messages, ensure_text, get_text_content  # noqa: E402

openai_llm_client = LLMClient()


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI Chat Completions API 兼容接口（走 DeepSeek）。"""
    _ = _resolve_ctx("openai_chat", request)
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")

    messages_raw = payload.get("messages", [])
    if not isinstance(messages_raw, list) or not messages_raw:
        raise HTTPException(status_code=400, detail="messages is required")

    # 转换 OpenAI 消息为 LangChain 消息（复用 build_chat_messages 的风格）
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    lc_messages = []
    for msg in messages_raw:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            lc_messages.append(SystemMessage(content=ensure_text(content)))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=ensure_text(content)))
        else:
            lc_messages.append(HumanMessage(content=ensure_text(content)))
    if not any(isinstance(m, HumanMessage) for m in lc_messages):
        lc_messages.append(HumanMessage(content=""))

    model = payload.get("model", "deepseek-chat")
    temperature = payload.get("temperature", 0.1)
    max_tokens = payload.get("max_tokens", payload.get("max_completion_tokens", 1000))
    stream = payload.get("stream", False)

    if not stream:
        response = openai_llm_client.invoke(
            messages=lc_messages,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response.content}, "finish_reason": "stop"}],
            "usage": {},
        }
    else:
        # 流式（SSE，OpenAI 格式）
        async def openai_stream():
            for chunk in openai_llm_client.stream(
                messages=lc_messages,
                model=model,
                temperature=temperature,
                max_completion_tokens=max_tokens,
            ):
                delta = str(chunk.content) if chunk.content else ""
                if delta:
                    data = {
                        "id": f"chatcmpl-{uuid.uuid4().hex}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(openai_stream(), media_type="text/event-stream")


def parse_args():
    parser = argparse.ArgumentParser(description="Start FastAPI server")
    parser.add_argument("-m", type=str, default="http", help="Run mode: http/flow/node")
    parser.add_argument("-n", type=str, default="", help="Node ID for single node run")
    parser.add_argument("-p", type=int, default=5000, help="HTTP server port")
    parser.add_argument("-i", type=str, default="", help="Input JSON string for flow/node mode")
    return parser.parse_args()


def parse_input(input_str: str) -> Dict[str, Any]:
    if not input_str:
        return {"user_message": "你好"}
    try:
        return json.loads(input_str)
    except json.JSONDecodeError:
        return {"user_message": input_str}


def start_http_server(port: int) -> None:
    logger.info(f"Start HTTP Server, Port: {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, workers=1)


if __name__ == "__main__":
    args = parse_args()
    if args.m == "http":
        start_http_server(args.p)
    elif args.m == "flow":
        payload = parse_input(args.i)
        result = asyncio.run(_run_graph(payload, new_context(method="flow")))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.m == "node" and args.n:
        payload = parse_input(args.i)
        func, input_cls, _, metadata = _find_node_func(args.n)
        if func is None or input_cls is None:
            print(json.dumps({"error": f"node '{args.n}' not found"}, ensure_ascii=False))
            raise SystemExit(1)
        builder = StateGraph(input_cls, input_schema=input_cls)
        builder.add_node("sn", func, metadata=metadata)
        builder.set_entry_point("sn")
        builder.add_edge("sn", END)
        result = asyncio.run(builder.compile().ainvoke(payload, config=_run_config(new_context(method="node"))))
        print(json.dumps(result, ensure_ascii=False, indent=2))
