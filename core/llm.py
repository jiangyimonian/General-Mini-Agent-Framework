"""弃用模块 - 请使用 general_mini_agent.

.. deprecated:: 0.9.0
    core 模块已弃用，请迁移至 general_mini_agent。
    此模块将在 1.0.0 版本中移除。
"""

import warnings

warnings.warn(
    "core 模块已弃用，请使用 'from general_mini_agent import ...'。"
    "此模块将在 1.0.0 版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

from general_mini_agent.llm import *  # noqa: F401,F403
