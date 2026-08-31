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

# Langfuse：复制 .env.example → .env，填入 LANGFUSE_* 后重启服务

