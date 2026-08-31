#!/bin/bash
# 启动签证客服 HTTP 服务（DeepSeek 直连，无 Coze 依赖）
cd "$(dirname "$0")/.." || exit 1

# 从项目 .env 读取配置（DEEPSEEK_API_KEY 等）；不存在则读 Hermes 的 key 兜底
if [ -f ".env" ]; then
  set -a; source .env; set +a
fi
if [ -z "$DEEPSEEK_API_KEY" ] && [ -f "$HOME/AppData/Local/hermes/.env" ]; then
  DEEPSEEK_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$HOME/AppData/Local/hermes/.env" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '\r')"
  export DEEPSEEK_API_KEY="$DEEPSEEK_KEY"
fi

# PG 数据库（可选：memory_saver 会自动退化到 MemorySaver）
if [ -z "$PGDATABASE_URL" ]; then
  export PGDATABASE_URL="postgresql://postgres:123456@127.0.0.1:5432/postgres"
fi

echo "DEEPSEEK_API_KEY length: ${#DEEPSEEK_API_KEY}"
exec .venv/Scripts/python.exe src/main.py -m http -p "${PORT:-5000}"
