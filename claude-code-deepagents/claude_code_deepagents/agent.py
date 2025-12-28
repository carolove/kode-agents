"""Core agent implementation using deepagents framework."""

from typing import Any, AsyncGenerator, Callable, Dict, List, Optional
from dataclasses import dataclass

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.state import CompiledStateGraph

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from claude_code_deepagents.config import AgentConfig


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
    - Sub-agent delegation (task)

    Args:
        config: Agent configuration

    Returns:
        Compiled LangGraph state graph representing the agent
    """
    model = create_model(config)

    # Use FilesystemBackend for real file operations
    backend = FilesystemBackend(
        root_dir=config.workspace_dir,
        virtual_mode=True,  # Use virtual paths for security
    )

    agent = create_deep_agent(
        model=model,
        system_prompt=config.system_prompt,
        backend=backend,
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
    ) -> AgentResponse:
        """Stream the agent's response with real-time event callbacks.

        Args:
            user_input: User's message
            on_todos: Callback when todos are updated
            on_text: Callback for text chunks
            on_tool_call: Callback for tool calls (name, args)

        Returns:
            Final AgentResponse with content and todos
        """
        config = {"configurable": {"thread_id": self.thread_id}}
        current_todos: List[Dict[str, Any]] = []
        final_content = ""

        async for chunk in self.agent.astream(
            {"messages": [HumanMessage(content=user_input)]},
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=config,
        ):
            # With subgraphs=True and dual stream_mode, chunk is (namespace, mode, data)
            if not isinstance(chunk, tuple) or len(chunk) != 3:
                continue

            _namespace, stream_mode, data = chunk

            # Handle updates stream - for todos
            if stream_mode == "updates":
                if not isinstance(data, dict):
                    continue
                # Extract todos from any node's output
                chunk_data = next(iter(data.values())) if data else None
                if chunk_data and isinstance(chunk_data, dict) and "todos" in chunk_data:
                    new_todos = chunk_data["todos"]
                    if new_todos != current_todos:
                        current_todos = new_todos
                        if on_todos:
                            on_todos(new_todos)

            # Handle messages stream - for text and tool calls
            elif stream_mode == "messages":
                if not isinstance(data, tuple) or len(data) != 2:
                    continue

                message, _metadata = data

                # Check for AI message content
                if hasattr(message, "content_blocks"):
                    for block in message.content_blocks:
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
                elif hasattr(message, "content") and isinstance(message.content, str):
                    if message.content:
                        final_content += message.content
                        if on_text:
                            on_text(message.content)

        return AgentResponse(content=final_content, todos=current_todos)

