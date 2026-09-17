"""pytest 全局配置与共享夹具。

为什么需要它：
    项目原先没有任何测试目录，且源码放在 `projects/src/` 下（见 pyproject.toml
    的 `pythonpath = ["src"]`）。评测脚本放在 `projects/eval/`，属于同一工程的
    另一个顶层包，默认不在 import 路径上。

    这里显式把 `src/` 和项目根 `projects/` 都加入 sys.path，好处是：
    1. 测试可以直接 `from eval.evaluator import ...`，与 `python eval/run.py`
       运行时看到的模块路径一致，避免"命令行能跑、pytest 不能跑"的假故障；
    2. 不依赖开发者是否已经 `pip install -e .`；
    3. 路径计算基于 __file__，在 CI 和本地都成立。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ -> projects/ -> src/ 与 projects/ 本身
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for _path in (SRC_DIR, PROJECT_ROOT):
    _p = str(_path)
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def fake_runtime():
    """节点签名要求 Runtime[Context]，这里给出最小可用替身。

    为什么不用 langgraph 的真实 Runtime：节点的纯规则逻辑只用到
    `runtime.context`（当前仅用于日志与 run_id），完整 Runtime 需要图运行环境，
    会让单元测试被迫启动整张图，反而掩盖了被测逻辑本身的问题。
    """
    from utils.context import Context

    class _FakeRuntime:
        def __init__(self) -> None:
            self.context = Context(method="unit_test")

    return _FakeRuntime()
