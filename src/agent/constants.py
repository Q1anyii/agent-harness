"""集中配置常量：可调参数统一出口。

各模块的默认值一律引用这里，避免魔法数字散落在多处；调参只改本文件。
注意：常量按用途分组，修改时同步核对语义（如 MAX_CONTEXT_TOKENS 是估算值，
estimate_tokens 对中文是低估，实际 token 约为估算的 2 倍）。
"""
from __future__ import annotations

# ---- Agent 循环 ----
MAX_ROUNDS = 8  # 单次问答最多工具调用轮次

# ---- 上下文窗口 ----
MAX_CONTEXT_TOKENS = 16000  # 估算 token 预算上限（DeepSeek 窗口 64K 级，中文低估约翻倍，留安全边际）
CHARS_PER_TOKEN = 2  # estimate_tokens 折中系数：len(text) // 2

# ---- 长期记忆 ----
MEMORY_RECALL_K = 10  # 每次召回 top-k
BM25_K1 = 1.5  # Okapi BM25 词频饱和系数
BM25_B = 0.75  # Okapi BM25 文档长度归一化系数
MEMORY_DECAY_FACTOR = 0.9  # 乘法衰减倍率：decay_factor ^ access_count
MEMORY_EXTRACT_RECENT_K = 10  # 记忆提取携带的最近消息条数（对齐 mem0 limit=10）

# ---- 流式事件 ----
EVENTS_MAX_PER_SESSION = 500  # 每会话事件队列保留上限（防内存膨胀）

# ---- 日志 ----
LOG_LIST_LIMIT = 200  # 日志查询默认返回条数

# ---- 外部请求 ----
LLM_TIMEOUT_SECONDS = 60.0  # LLM 客户端超时
HTTP_TIMEOUT_SECONDS = 10.0  # 联网工具请求超时
TOOL_TIMEOUT_SECONDS = 10.0  # 单个工具执行总超时（asyncio.wait_for 兜底，防工具实现卡死整轮）
SEARCH_MAX_RESULTS = 5  # 搜索结果条数上限

# ---- 存储 / 服务 ----
DEFAULT_SESSION_DB = "data/agent-harness.db"  # SQLite 默认库文件路径
DEFAULT_PORT = 8000  # 默认监听端口（可用 PORT 环境变量覆盖）
