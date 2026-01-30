"""
wall 包初始化文件
"""

# 1. 定义单一事实来源的版本号
__version__ = "0.1.0"

# 2. 暴露核心业务逻辑 (方便其他 Python 脚本直接 import wall; wall.run(...))
from .app import run_app

__all__ = ["run_app", "__version__"]
