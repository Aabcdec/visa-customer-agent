# 签证客服智能体（后端 + H5）

Python / LangGraph 签证客服 Agent 工作流，含静态 H5 前端。LLM 走 DeepSeek 直连，无 Coze 平台依赖。

## 目录

| 目录 | 说明 |
|------|------|
| `projects/` | 后端：LangGraph 工作流、节点、本地知识库资产 |
| `h5/` | 静态 H5 聊天页；`worker/` 为 Cloudflare 代理（国内可能不可达） |
| `docs/` | 面试文档与简历补充说明 |

## 后端

```bash
cd projects
# 复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
uv sync
bash scripts/http_run.sh -p 5000   # 或 scripts/run_local_deepseek.sh
```

入口与编排：`projects/src/main.py`（FastAPI 服务）
图：`projects/src/graphs/graph.py`
节点：`projects/src/graphs/nodes/`

## H5

1. 复制 `h5/config.example.js` 为 `h5/config.js`，填写 `apiUrl`（指向你的后端 `/run` 地址；勿直连不可达的第三方代理）。
2. 用任意静态托管上传 `h5/`（不要上传 `.env`）。

## 安全

- 不要提交 `.env`、`config.js` 中的 Token。
- 仓库仅保留 `config.example.js`、`.env.example`。
