#!/usr/bin/env python3
"""加载项目环境变量 - 从项目 .env 文件读取并输出 export 语句。

替代原 coze_workload_identity 实现：本地运行不再依赖 Coze 平台，
环境变量统一从项目根目录的 .env 文件加载（也兼容系统环境变量覆盖）。
用法: eval $(python load_env.py)
"""
import os
import sys
from pathlib import Path


def main() -> int:
    # 项目根：本文件在 projects/scripts/ 下
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"

    if not env_file.exists():
        print("# .env not found, using system environment only", file=sys.stderr)
        return 0

    loaded = 0
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # 系统环境变量优先，不覆盖已有值
        if key and key not in os.environ:
            escaped = value.replace("'", "'\\''")
            print(f"export {key}='{escaped}'")
            loaded += 1

    print(f"# Successfully loaded {loaded} environment variables", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
