# 签证客服智能体（后端 + H5）

Python / LangGraph 签证客服 Agent 工作流，含静态 H5 前端。

## 目录

| 目录 | 说明 |
|------|------|
| `projects/` | 后端：LangGraph 工作流、节点、知识库资产、Coze Coding 工程 |
| `h5/` | 静态 H5 聊天页；`worker/` 为 Cloudflare 代理（国内可能不可达） |
| `docs/` | 面试文档与简历补充说明 |

## 后端

```bash
cd projects
# 按 Coze Coding / 本地说明安装依赖并运行
```

入口与编排：`projects/src/graphs/graph.py`  
节点：`projects/src/graphs/nodes/`

## H5

1. 复制 `h5/config.example.js` 为 `h5/config.js`，填写 `apiUrl`（国内建议用阿里云 FC 等可访问代理，勿直连 `coze.site`，`*.workers.dev` 国内常不可用）。
2. 用任意静态托管上传 `h5/`（不要上传 `.env`）。

## 安全

- 不要提交 `.env`、`config.js` 中的 Token。
- 仓库仅保留 `config.example.js`、`.env.example`。
