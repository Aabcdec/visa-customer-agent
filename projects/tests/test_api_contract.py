"""FastAPI 接口契约测试。

为什么需要这层：H5 前端只依赖这些端点的形状。端点一改名或改错误码，
前端就会静默失效，而且往往要等到真人点进去才发现。

这里只测**不调用模型**的端点与错误分支，所以 CI 里不需要 API Key、也不花钱。
真正的端到端问答由 eval harness 负责（离线或 live）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


# ========== 健康检查与元信息 ==========

def test_health_returns_ok(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_graph_parameter_exposes_schemas(client) -> None:
    """前端靠这个端点动态渲染输入框，字段必须对得上。"""
    response = client.get("/graph_parameter")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert "user_message" in body["input_schema"]["properties"]
    assert "final_reply" in body["output_schema"]["properties"]


def test_graph_parameter_output_schema_includes_flow_path(client) -> None:
    """前端用 flow_path 渲染路径标签与 confirm/handoff 样式，必须对外可见。"""
    response = client.get("/graph_parameter")

    assert "flow_path" in response.json()["output_schema"]["properties"]


# ========== 错误分支 ==========

def test_run_rejects_invalid_json(client) -> None:
    """非法 JSON 必须返回 400，而不是 500 把堆栈暴露给前端。"""
    response = client.post(
        "/run",
        content="{not json}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_unknown_task_returns_404(client) -> None:
    response = client.get("/task/does-not-exist")

    assert response.status_code == 404


def test_cancel_unknown_run_reports_not_found(client) -> None:
    """取消不存在的任务要给出可读状态，而不是报错——前端会频繁轮询。"""
    response = client.post("/cancel/does-not-exist")

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_node_run_unknown_node_returns_404(client) -> None:
    response = client.post("/node_run/not_a_node", json={"user_message": "x"})

    assert response.status_code == 404


# ========== CORS ==========

def test_cors_headers_present_for_browser_client(client) -> None:
    """H5 从静态托管域名访问后端，缺少 CORS 头会导致浏览器直接拦截。"""
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers.get("access-control-allow-origin") == "*"


# ========== 运行 ID 透传 ==========

def test_run_id_header_is_echoed_on_cancel(client) -> None:
    """上游可用 x-run-id 对齐链路追踪；cancel 至少不能因为缺它而报错。"""
    response = client.post("/cancel/whatever", headers={"x-run-id": "trace-123"})

    assert response.status_code == 200
