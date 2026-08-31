#!/bin/bash
# 启动签证客服 HTTP 服务（DeepSeek 直连模式）
cd "$(dirname "$0")/.." || exit 1

# 从 Hermes .env 读取 DeepSeek key 注入 Coze SDK 兼容变量
DEEPSEEK_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$HOME/AppData/Local/hermes/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')"
export COZE_WORKLOAD_IDENTITY_API_KEY="$DEEPSEEK_KEY"
# LLMClient 实际用 MODEL_BASE_URL；BASE_URL 是 Config 初始化必填项（KnowledgeClient 用），统一指 DeepSeek
export COZE_INTEGRATION_BASE_URL="https://api.deepseek.com"
export COZE_INTEGRATION_MODEL_BASE_URL="https://api.deepseek.com"
export PGDATABASE_URL="postgresql://postgres:123456@127.0.0.1:5432/postgres"

echo "COZE_WORKLOAD_IDENTITY_API_KEY length: ${#DEEPSEEK_KEY}"
exec .venv/Scripts/python.exe src/main.py -m http -p 5000
