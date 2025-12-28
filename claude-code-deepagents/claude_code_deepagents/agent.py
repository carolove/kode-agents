"""Core agent implementation using deepagents framework."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph.state import CompiledStateGraph

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from claude_code_deepagents.config import AgentConfig


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

    def invoke(self, user_input: str) -> str:
        """Process a single user input and return the response.

        Args:
            user_input: User's message

        Returns:
            Agent's response text
        """
        result = self.agent.invoke(
            {"messages": [HumanMessage(content=user_input)]},
            config={"configurable": {"thread_id": self.thread_id}},
        )

        # Extract the last AI message
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg.content
        return ""

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

