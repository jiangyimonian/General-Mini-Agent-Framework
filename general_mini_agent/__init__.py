"""General Mini Agent Framework - 正式命名空间。"""

__version__ = "1.6.0"

from .agent import Agent, AgentConfig, AgentResult, StreamEvent, TraceEvent
from .agent_protocol import AgentStopReason
from .async_agent import AsyncAgent
from .async_debate import (
    AsyncDebate,
    AsyncDebateAgentEvent,
    AsyncDebateConfig,
    AsyncDebateDoneEvent,
    AsyncDebateRole,
    AsyncDebateRoundStartEvent,
    AsyncDebateSpeakerEvent,
    AsyncDebateStreamEvent,
    AsyncParticipantExecution,
    create_async_debate,
)
from .async_llm import AsyncChatModel, AsyncLLM, AsyncStreamingChatModel
from .async_long_term_memory import (
    AsyncChromaMemoryStore,
    AsyncInMemoryLongTermStore,
    AsyncLongTermMemoryStore,
)
from .async_tools import AsyncToolRegistry
from .compression import (
    AutoCompressingConversation,
    CompressingContextPolicy,
    CompressionResult,
    CompressionStrategy,
    SimpleTruncationStrategy,
    SummarizationStrategy,
)
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
from .permissions import (
    AllowAllPolicy,
    AskPolicy,
    CompositePolicy,
    ConditionalPolicy,
    DenyAllPolicy,
    PermissionPolicy,
    PermissionPolicyToAuthorizationAdapter,
    RiskBasedPolicy,
    ToolAllowlistPolicy,
    ToolBlocklistPolicy,
    ToolPermissionRequest,
    ToolPermissionResponse,
)
from .providers import (
    DeepSeekAdapter,
    ModelCapabilityError,
    OpenAICompatibleAdapter,
    ProviderAdapter,
    ProviderCapabilities,
)
from .retry import RetryPolicy, execute_with_retry
from .session import (
    Session,
    SessionMetadata,
    conversation_from_session,
    delete_session,
    get_session_dir,
    get_session_path,
    list_sessions,
    load_session,
    save_session,
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
from .tools_project import (
    ProjectToolBoundaryPolicy,
    ToolRuntimeContext,
    create_project_tool_policy,
    create_project_tools,
    get_risk_category_for_tool,
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
    LoopNode,
    NodeResult,
    ParallelErrorPolicy,
    ParallelNode,
    SequenceNode,
    Workflow,
    WorkflowNode,
    WorkflowResult,
    WorkflowStopReason,
)
from .workflow_adapters import AgentNode, AsyncAgentNode, AsyncDebateNode, DebateNode

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
    # AsyncDebate
    "AsyncDebate",
    "AsyncDebateAgentEvent",
    "AsyncDebateConfig",
    "AsyncDebateDoneEvent",
    "AsyncDebateRole",
    "AsyncDebateRoundStartEvent",
    "AsyncDebateSpeakerEvent",
    "AsyncDebateStreamEvent",
    "AsyncParticipantExecution",
    "create_async_debate",
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
    # 异步长期记忆
    "AsyncLongTermMemoryStore",
    "AsyncInMemoryLongTermStore",
    "AsyncChromaMemoryStore",
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
    # 重试策略
    "RetryPolicy",
    "execute_with_retry",
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
    "LoopNode",
    # 工作流适配器
    "AsyncAgentNode",
    "AgentNode",
    "DebateNode",
    "AsyncDebateNode",
    # 日志
    "get_logger",
    "safe_log_fields",
    # 项目工具
    "ToolRuntimeContext",
    "create_project_tools",
    "create_project_tool_policy",
    "get_risk_category_for_tool",
    "ProjectToolBoundaryPolicy",
    # 权限与安全边界
    "AllowAllPolicy",
    "AskPolicy",
    "CompositePolicy",
    "ConditionalPolicy",
    "DenyAllPolicy",
    "PermissionPolicy",
    "PermissionPolicyToAuthorizationAdapter",
    "RiskBasedPolicy",
    "ToolAllowlistPolicy",
    "ToolBlocklistPolicy",
    "ToolPermissionRequest",
    "ToolPermissionResponse",
    # 会话管理
    "Session",
    "SessionMetadata",
    "conversation_from_session",
    "delete_session",
    "get_session_dir",
    "get_session_path",
    "list_sessions",
    "load_session",
    "save_session",
    # 上下文压缩
    "AutoCompressingConversation",
    "CompressionResult",
    "CompressionStrategy",
    "CompressingContextPolicy",
    "SimpleTruncationStrategy",
    "SummarizationStrategy",
]