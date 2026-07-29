"""General Mini Agent Framework - 正式命名空间。"""

from .agent import Agent, AgentConfig, AgentResult, StreamEvent, TraceEvent
from .agent_protocol import AgentStopReason
from .async_agent import AsyncAgent
from .async_llm import AsyncChatModel, AsyncLLM, AsyncStreamingChatModel
from .async_tools import AsyncToolRegistry
from .context import (
    ApproximateTokenCounter,
    ContextBudgetExceeded,
    ContextPolicy,
    SummarizingContext,
    TokenBudgetContext,
    TokenCounter,
)
from .debate import (
    ConvergenceCheck,
    Debate,
    DebateAgentEvent,
    DebateConfig,
    DebateDoneEvent,
    DebateResult,
    DebateRole,
    DebateRound,
    DebateRoundStartEvent,
    DebateSpeakerEvent,
    DebateStopReason,
    DebateStreamEvent,
    DebateTurn,
    create_debate,
)
from .events import (
    EventCollector,
    EventSink,
    RunContext,
    RunEvent,
    RunEventEmitter,
)
from .llm import (
    LLM,
    ChatModel,
    LLMConfig,
    LLMResponse,
    ModelRequestError,
    StreamChunk,
    StreamingChatModel,
    ToolCallDelta,
)
from .logging import get_logger, safe_log_fields
from .long_term_memory import (
    ChromaMemoryStore,
    InMemoryLongTermStore,
    LongTermMemoryStore,
    MemoryNamespace,
    MemoryQuery,
    MemoryRecord,
    MemoryRecordNotFound,
    MemoryScope,
    MemoryStoreError,
    MetadataValue,
    build_memory_context,
    create_memory_record,
)
from .memory import ConversationMemory, InMemoryConversation
from .providers import (
    DeepSeekAdapter,
    ModelCapabilityError,
    OpenAICompatibleAdapter,
    ProviderAdapter,
    ProviderCapabilities,
)
from .tools import (
    JSONValue,
    Tool,
    ToolAuthorizationDecision,
    ToolAuthorizationPolicy,
    ToolAuthorizationRequest,
    ToolExecutionResult,
    ToolRegistry,
    tool,
)
from .trace import (
    compare_traces_to_html,
    debate_to_html,
    export_trace_html,
    render_html,
    trace_to_html,
)
from .trace import (
    export_trace_html as export_trace,
)
from .trace_json import (
    TraceDocument,
    export_trace_json,
    trace_from_json,
    trace_to_json,
)
from .workflow import (
    ConditionalNode,
    NodeResult,
    ParallelErrorPolicy,
    ParallelNode,
    SequenceNode,
    Workflow,
    WorkflowNode,
    WorkflowResult,
    WorkflowStopReason,
)
from .workflow_adapters import AgentNode, AsyncAgentNode, DebateNode

# isort: split
# Experimental compatibility exports; not part of the stable API.
from .memory import LongTermMemory, SlidingWindowMemory

__all__ = [
    # 异步模型与 Agent
    "AsyncChatModel",
    "AsyncLLM",
    "AsyncStreamingChatModel",
    "AsyncToolRegistry",
    "AsyncAgent",
    # 同步模型与 Agent
    "ChatModel",
    "LLM",
    "LLMConfig",
    "LLMResponse",
    "ModelRequestError",
    "StreamChunk",
    "StreamingChatModel",
    "ToolCallDelta",
    # 提供商适配器
    "ProviderCapabilities",
    "ProviderAdapter",
    "OpenAICompatibleAdapter",
    "DeepSeekAdapter",
    "ModelCapabilityError",
    # 工具
    "tool",
    "Tool",
    "ToolRegistry",
    "ToolExecutionResult",
    "JSONValue",
    "ToolAuthorizationRequest",
    "ToolAuthorizationDecision",
    "ToolAuthorizationPolicy",
    # Agent
    "Agent",
    "AgentConfig",
    "AgentResult",
    "AgentStopReason",
    "StreamEvent",
    "TraceEvent",
    # Debate
    "ConvergenceCheck",
    "Debate",
    "DebateAgentEvent",
    "DebateConfig",
    "DebateDoneEvent",
    "DebateResult",
    "DebateRole",
    "DebateRound",
    "DebateRoundStartEvent",
    "DebateSpeakerEvent",
    "DebateStopReason",
    "DebateStreamEvent",
    "DebateTurn",
    "create_debate",
    # 事件
    "RunContext",
    "RunEvent",
    "EventSink",
    "EventCollector",
    "RunEventEmitter",
    # 上下文
    "TokenCounter",
    "ApproximateTokenCounter",
    "ContextPolicy",
    "TokenBudgetContext",
    "SummarizingContext",
    "ContextBudgetExceeded",
    # 记忆
    "ConversationMemory",
    "InMemoryConversation",
    # 长期记忆
    "MemoryScope",
    "MetadataValue",
    "MemoryNamespace",
    "MemoryRecord",
    "MemoryQuery",
    "LongTermMemoryStore",
    "MemoryStoreError",
    "MemoryRecordNotFound",
    "InMemoryLongTermStore",
    "ChromaMemoryStore",
    "create_memory_record",
    "build_memory_context",
    # JSON trace
    "TraceDocument",
    "trace_to_json",
    "trace_from_json",
    "export_trace_json",
    # HTML trace
    "trace_to_html",
    "export_trace_html",
    "compare_traces_to_html",
    "render_html",
    "debate_to_html",
    "export_trace",
    # 兼容导出
    "SlidingWindowMemory",
    "LongTermMemory",
    # 工作流
    "Workflow",
    "WorkflowNode",
    "WorkflowResult",
    "NodeResult",
    "WorkflowStopReason",
    "SequenceNode",
    "ParallelNode",
    "ParallelErrorPolicy",
    "ConditionalNode",
    # 工作流适配器
    "AsyncAgentNode",
    "AgentNode",
    "DebateNode",
    # 日志
    "get_logger",
    "safe_log_fields",
]