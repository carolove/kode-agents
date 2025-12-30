"""Core agent implementation using deepagents framework."""

from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Overwrite

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from claude_code_deepagents.config import AgentConfig
from claude_code_deepagents.subagents import create_subagents_from_names
from claude_code_deepagents.skills import SkillsMiddleware
from claude_code_deepagents.tools import web_search, fetch_url


def unwrap_overwrite(value: Any) -> Any:
    """Unwrap Overwrite type if present.

    Args:
        value: Value that may be wrapped in Overwrite

    Returns:
        The unwrapped value
    """
    if isinstance(value, Overwrite):
        return value.value
    return value


def safe_len(obj: Any) -> int:
    """Safely get the length of an object.

    Args:
        obj: Object to measure

    Returns:
        Length of the object, or length of str representation
    """
    # Unwrap Overwrite if present
    obj = unwrap_overwrite(obj)

    if obj is None:
        return 0
    if isinstance(obj, str):
        return len(obj)
    if hasattr(obj, "__len__"):
        try:
            return len(obj)
        except TypeError:
            pass
    # Fallback to string representation
    return len(str(obj))


def estimate_message_chars(message) -> int:
    """Estimate the character count of a message for context tracking.

    Args:
        message: A langchain message object

    Returns:
        Estimated character count
    """
    # Handle Overwrite wrapper
    message = unwrap_overwrite(message)

    if message is None:
        return 0

    chars = 0
    if hasattr(message, "content"):
        content = unwrap_overwrite(message.content)
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            # Handle content blocks (tool calls, etc.)
            for block in content:
                block = unwrap_overwrite(block)
                if isinstance(block, dict):
                    if "text" in block:
                        chars += safe_len(block["text"])
                    elif "input" in block:
                        chars += safe_len(block["input"])
                elif isinstance(block, str):
                    chars += len(block)
        elif content is not None:
            # Fallback for other types
            chars += safe_len(content)
    if hasattr(message, "tool_calls") and message.tool_calls:
        tool_calls = unwrap_overwrite(message.tool_calls)
        if tool_calls:
            for tc in tool_calls:
                tc = unwrap_overwrite(tc)
                if isinstance(tc, dict):
                    chars += safe_len(tc.get("args", {}))
    return chars


@dataclass
class ContextStats:
    """Statistics about context/message history."""
    message_count: int = 0
    total_chars: int = 0
    human_messages: int = 0
    ai_messages: int = 0
    tool_messages: int = 0
    subagent_calls: int = 0
    subagent_result_chars: int = 0  # Characters added by subagent results

    def __str__(self) -> str:
        return (
            f"[Context] msgs={self.message_count} chars={self.total_chars:,} "
            f"(human={self.human_messages} ai={self.ai_messages} tool={self.tool_messages}) "
            f"subagents={self.subagent_calls} subagent_result_chars={self.subagent_result_chars:,}"
        )


@dataclass
class AgentResponse:
    """Response from agent with todos."""
    content: str
    todos: List[Dict[str, Any]]


@dataclass
class StreamEvent:
    """Event emitted during streaming."""
    event_type: str  # "text", "todos", "tool_call", "done"
    data: Any


def create_model(config: AgentConfig) -> ChatAnthropic:
    """Create the LLM model instance.

    Args:
        config: Agent configuration

    Returns:
        ChatAnthropic model instance
    """
    return ChatAnthropic(
        model_name=config.model_name,
        max_tokens=config.max_tokens,
        api_key=config.api_key,
        base_url=config.base_url,
    )


def create_coding_agent(config: AgentConfig) -> CompiledStateGraph:
    """Create a coding agent using deepagents framework.

    This agent has access to:
    - File operations (ls, read_file, write_file, edit_file, glob, grep)
    - Shell execution (execute)
    - Task management (write_todos, read_todos)
    - Sub-agent delegation (task) via subagents
    - Skills system for domain-specific knowledge

    Available subagents:
    - explore: For exploring and analyzing codebases (read-only focus)
    - code: For implementing features and fixing bugs (full access)
    - plan: For creating implementation plans (read-only focus)

    Args:
        config: Agent configuration

    Returns:
        Compiled LangGraph state graph representing the agent
    """
    model = create_model(config)

    # Use FilesystemBackend for real file operations
    backend = FilesystemBackend(
        root_dir=config.workspace_dir,
        virtual_mode=False,  # Use virtual paths for security
    )

    # Create subagents using official deepagents method
    subagents = None
    if config.enable_subagents:
        # Add web search tools to subagents
        additional_tools = [web_search, fetch_url]
        subagents = create_subagents_from_names(
            names=config.subagent_types,
            workspace_dir=config.workspace_dir,
            additional_tools=additional_tools,
        )

    # Build middleware list
    middleware = []

    # Add skills middleware if enabled
    if config.enable_skills:
        skills_middleware = SkillsMiddleware(
            user_skills_dir=config.user_skills_dir,
            project_skills_dir=config.project_skills_dir,
            assistant_id=config.assistant_id,
        )
        middleware.append(skills_middleware)

    agent = create_deep_agent(
        model=model,
        system_prompt=config.system_prompt,
        backend=backend,
        subagents=subagents,
        middleware=middleware,
    )

    return agent


class CodingAgentSession:
    """Interactive session for the coding agent."""

    def __init__(self, config: AgentConfig):
        """Initialize the agent session.

        Args:
            config: Agent configuration
        """
        self.config = config
        self.agent = create_coding_agent(config)
        self.thread_id = "main"
        self._context_stats = ContextStats()

    def get_context_stats(self) -> ContextStats:
        """Get current context statistics.

        Returns:
            Current ContextStats
        """
        return self._context_stats

    def _compute_context_stats(self, messages) -> ContextStats:
        """Compute context statistics from message history.

        Args:
            messages: List of messages from agent state (may be wrapped in Overwrite)

        Returns:
            ContextStats with computed values
        """
        # Unwrap Overwrite if present
        messages = unwrap_overwrite(messages)

        stats = ContextStats()

        if messages is None:
            return stats

        # Safely get message count
        stats.message_count = safe_len(messages)

        # Handle case where messages is not iterable
        if not hasattr(messages, "__iter__"):
            return stats

        for msg in messages:
            # Unwrap each message if needed
            msg = unwrap_overwrite(msg)

            chars = estimate_message_chars(msg)
            stats.total_chars += chars

            if isinstance(msg, HumanMessage):
                stats.human_messages += 1
            elif isinstance(msg, AIMessage):
                stats.ai_messages += 1
                # Check for subagent (task) tool calls
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    tool_calls = unwrap_overwrite(tool_calls)
                    if tool_calls:
                        for tc in tool_calls:
                            tc = unwrap_overwrite(tc)
                            if isinstance(tc, dict) and tc.get("name") == "task":
                                stats.subagent_calls += 1
            elif isinstance(msg, ToolMessage):
                stats.tool_messages += 1
                # Check if this is a subagent result
                msg_name = getattr(msg, "name", None)
                if msg_name == "task":
                    stats.subagent_result_chars += chars

        return stats

    def invoke(self, user_input: str) -> AgentResponse:
        """Process a single user input and return the response with todos.

        Args:
            user_input: User's message

        Returns:
            AgentResponse containing text and todos
        """
        result = self.agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config={"configurable": {"thread_id": self.thread_id}},
        )

        # Extract todos from state
        todos = result.get("todos", [])

        # Extract the last AI message
        content = ""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                break

        return AgentResponse(content=content, todos=todos)

    async def ainvoke(self, user_input: str) -> str:
        """Async version of invoke.

        Args:
            user_input: User's message

        Returns:
            Agent's response text
        """
        result = await self.agent.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config={"configurable": {"thread_id": self.thread_id}},
        )

        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg.content
        return ""

    def stream(self, user_input: str):
        """Stream the agent's response.

        Args:
            user_input: User's message

        Yields:
            Chunks of the agent's response
        """
        for chunk in self.agent.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config={"configurable": {"thread_id": self.thread_id}},
        ):
            if "messages" in chunk:
                for msg in chunk["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content

    async def astream_with_events(
        self,
        user_input: str,
        on_todos: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_context_stats: Optional[Callable[[ContextStats, ContextStats, Optional[str]], None]] = None,
    ) -> AgentResponse:
        """Stream the agent's response with real-time event callbacks.

        Args:
            user_input: User's message
            on_todos: Callback when todos are updated
            on_text: Callback for text chunks
            on_tool_call: Callback for tool calls (name, args)
            on_context_stats: Callback for context stats updates (before, after, event_type)
                event_type can be: "start", "subagent_call", "subagent_result", "end"

        Returns:
            Final AgentResponse with content and todos
        """
        config = {"configurable": {"thread_id": self.thread_id}}
        current_todos: List[Dict[str, Any]] = []
        final_content = ""

        # Track context stats
        stats_before = ContextStats(
            message_count=self._context_stats.message_count,
            total_chars=self._context_stats.total_chars,
            human_messages=self._context_stats.human_messages,
            ai_messages=self._context_stats.ai_messages,
            tool_messages=self._context_stats.tool_messages,
            subagent_calls=self._context_stats.subagent_calls,
            subagent_result_chars=self._context_stats.subagent_result_chars,
        )

        # Report initial stats
        if on_context_stats:
            on_context_stats(stats_before, stats_before, "start")

        async for chunk in self.agent.astream(
            {"messages": [HumanMessage(content=user_input)]},
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=config,
        ):
            # With subgraphs=True and dual stream_mode, chunk is (namespace, mode, data)
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            namespace, stream_mode, data = chunk

            # Handle updates stream - for todos and context tracking
            if stream_mode == "updates":
                if not isinstance(data, dict):
                    continue
                # Extract todos from any node's output
                chunk_data = next(iter(data.values())) if data else None
                if chunk_data and isinstance(chunk_data, dict):
                    if "todos" in chunk_data:
                        new_todos = chunk_data["todos"]
                        if new_todos != current_todos:
                            current_todos = new_todos
                            if on_todos:
                                on_todos(new_todos)

                    # Track messages for context stats
                    if "messages" in chunk_data and on_context_stats:
                        messages = chunk_data["messages"]
                        stats_after = self._compute_context_stats(messages)

                        # Check if this is from a subagent (namespace will be non-empty tuple)
                        is_subagent = len(namespace) > 0
                        if is_subagent:
                            # This is subagent activity - track but note it's isolated
                            on_context_stats(stats_before, stats_after, "subagent_activity")
                        else:
                            # Main agent context update
                            self._context_stats = stats_after
                            on_context_stats(stats_before, stats_after, "update")

            # Handle messages stream - for text and tool calls
            elif stream_mode == "messages":
                if not isinstance(data, tuple) or len(data) != 2:
                    continue

                message, _metadata = data

                # Check for AI message content
                if hasattr(message, "content_blocks"):
                    for block in message.content_blocks:
                        # Handle both dict blocks and string blocks
                        if isinstance(block, str):
                            # String block - treat as text
                            if block:
                                final_content += block
                                if on_text:
                                    on_text(block)
                            continue

                        # Dict block - check type
                        if not isinstance(block, dict):
                            continue

                        block_type = block.get("type")
                        if block_type == "text":
                            text = block.get("text", "")
                            if text:
                                final_content += text
                                if on_text:
                                    on_text(text)
                        elif block_type in ("tool_call_chunk", "tool_call"):
                            # Complete tool call
                            name = block.get("name", "")
                            args = block.get("args", {})
                            if name and on_tool_call:
                                on_tool_call(name, args)
                                # Track subagent calls
                                if name == "task" and on_context_stats:
                                    self._context_stats.subagent_calls += 1
                                    on_context_stats(stats_before, self._context_stats, "subagent_call")
                elif hasattr(message, "content") and isinstance(message.content, str):
                    if message.content:
                        final_content += message.content
                        if on_text:
                            on_text(message.content)

        # Report final stats
        if on_context_stats:
            on_context_stats(stats_before, self._context_stats, "end")

        return AgentResponse(content=final_content, todos=current_todos)

