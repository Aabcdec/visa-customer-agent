# 项目结构说明

# 本地运行
## 运行流程
bash scripts/local_run.sh -m flow

## 运行节点
bash scripts/local_run.sh -m node -n node_name

# 启动HTTP服务
bash scripts/http_run.sh -m http -p 5000

# 黄金集评测（需服务已启动）
# python eval/run.py --base-url http://127.0.0.1:5000

# 环境变量
# 复制 .env.example → .env，填写 DEEPSEEK_API_KEY（必填）、LANGFUSE_*（可选）、PGDATABASE_URL（可选）
# 无 Coze 依赖：LLM 走 DeepSeek 直连（langchain-openai），知识库走本地 assets/*.md 关键词检索
