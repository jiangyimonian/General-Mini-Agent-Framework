"""弃用命名空间 - 所有导出均来自 general_mini_agent。

.. deprecated:: 0.9.0
    core 命名空间已弃用，请迁移至 general_mini_agent。
    此命名空间将在 1.0.0 版本中移除。
"""

import warnings

# 发出弃用警告
warnings.warn(
    "core 命名空间已弃用，请使用 'from general_mini_agent import ...'。"
    "此命名空间将在 1.0.0 版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export 所有符号
from general_mini_agent import *  # noqa: F401,F403
from general_mini_agent import __all__

__all__ = __all__