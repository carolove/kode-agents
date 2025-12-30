"""Custom tools for claude-code-deepagents."""

from typing import Any, Literal
import os

import requests
from tavily import TavilyClient


# Initialize Tavily client if API key is available
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=TAVILY_API_KEY) if TAVILY_API_KEY else None


def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Search the web using Tavily for current information and documentation.

    This tool searches the web and returns relevant results. After receiving results,
    you MUST synthesize the information into a natural, helpful response for the user.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: Search topic type - "general" for most queries, "news" for current events
        include_raw_content: Include full page content (warning: uses more tokens)

    Returns:
        Dictionary containing:
        - results: List of search results, each with:
            - title: Page title
            - url: Page URL
            - content: Relevant excerpt from the page
            - score: Relevance score (0-1)
        - query: The original search query

    IMPORTANT: After using this tool:
    1. Read through the 'content' field of each result
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. Cite sources by mentioning the page titles or URLs
    5. NEVER show the raw JSON to the user - always provide a formatted response
    """
    if tavily_client is None:
        return {
            "error": "Tavily API key not configured. Please set TAVILY_API_KEY environment variable.",
            "query": query,
        }

    try:
        return tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )
    except Exception as e:
        return {"error": f"Web search error: {e!s}", "query": query}


def fetch_url(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch content from a URL and convert to markdown.

    Args:
        url: URL to fetch content from
        timeout: Request timeout in seconds

    Returns:
        Dictionary with:
        - success: Whether the request succeeded
        - status_code: HTTP status code
        - content: Markdown content from the URL
        - url: The requested URL
    """
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            # For simplicity, return text content
            # In production, you might want to use markdownify or similar
            return {
                "success": True,
                "status_code": response.status_code,
                "content": response.text[:10000],  # Limit content size
                "url": url,
            }
        else:
            return {
                "success": False,
                "status_code": response.status_code,
                "content": f"HTTP Error: {response.status_code}",
                "url": url,
            }
    except Exception as e:
        return {
            "success": False,
            "status_code": 0,
            "content": f"Request error: {e!s}",
            "url": url,
        }


# Export tools
__all__ = ["web_search", "fetch_url"]