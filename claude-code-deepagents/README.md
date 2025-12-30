# claude-code-deepagents

A coding agent based on deepagents and langchain framework, providing Claude Code-like functionality with enhanced skill system and subagent delegation.

## Features

- **Interactive Coding Agent**: Natural language interaction for code tasks
- **Skill System**: Progressive disclosure skills following Anthropic's Agent Skills pattern
- **Subagent Delegation**: Three specialized subagents for focused tasks
- **Context Management**: Real-time context statistics and isolation
- **File Operations**: Full filesystem access (read, write, edit, search)
- **Shell Execution**: Safe shell command execution
- **Todo Management**: Colored todo tracking for multi-step tasks

## Installation

```bash
# Install from current directory
pip install .

# Or install in development mode
pip install -e .
```

## Configuration

1. Set environment variables in `.env` file:
   ```bash
   ANTHROPIC_API_KEY=your_api_key
   ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
   ANTHROPIC_MODEL=deepseek-chat
   TAVILY_API_KEY=your_tavily_key  # for web-search skill
   ```

2. Or set environment variables directly:
   ```bash
   export ANTHROPIC_API_KEY=your_api_key
   export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
   ```

## Usage

### Interactive Mode
```bash
# Start the interactive agent
claude-code-deepagents

# Or run directly
python -m claude_code_deepagents
```

### Commands in Interactive Mode
- `stats` - Show current context statistics
- `skills list` - List all available skills
- `exit` or `quit` - Exit the session

### Available Subagents
Use the `task` tool to delegate to specialized subagents:
- **explore**: Read-only agent for exploring codebases and searching
- **code**: Full coding agent for implementing features and fixing bugs
- **plan**: Planning agent for creating implementation strategies

## Skill System

### Skill Locations
- **User Skills**: `~/.deepagents/claude-code/skills/`
- **Project Skills**: `./.deepagents/skills/` (overrides user skills)

### Creating Skills
Each skill is a directory containing a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: skill-name
description: Brief description of what this skill does
---

# Skill Name

## When to Use
- When the user asks for X
- When you need to do Y

## Step-by-step Instructions
1. First step
2. Second step
```

### Available Skills
This project includes two example skills:
- **code-review**: Systematic code review with checklist
- **web-search**: Web research using Tavily API

## Architecture

### Core Modules
- `config.py` - Configuration management (`AgentConfig`)
- `agent.py` - Core agent implementation (`CodingAgentSession`)
- `main.py` - Interactive REPL interface
- `skills/` - Skill loading and middleware
- `subagents/` - Subagent definitions

### Dependencies
- `deepagents>=0.1.0` - Core agent framework
- `langchain>=0.3.0` - LLM application framework
- `langchain-anthropic>=0.3.0` - Anthropic integration
- `langgraph>=0.2.0` - Graph state management
- `pydantic>=2.0.0` - Data validation

## Development

### Setup Development Environment
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install with development dependencies
pip install -e .[dev]
```

### Running Tests
```bash
pytest
```

### Code Quality
```bash
ruff check .
ruff format .
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built on the [deepagents](https://github.com/microsoft/deepagents) framework
- Implements Anthropic's Agent Skills pattern
- Inspired by Claude Code's interactive coding experience