# pip install fastapi uvicorn langgraph langchain langchain-openai langchain-community chromadb tiktoken langchain-mcp-adapters

import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Load environment variables from .env file
load_dotenv()

from typing import List, TypedDict
from typing_extensions import Annotated
from fastapi import FastAPI
from pydantic import BaseModel

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

# --- OpenAI (chat + embeddings) ---
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages

# ===== Config =====
WINDOW = 8
TOP_K = 4
# Use absolute path to ensure database file is created in the correct location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_URL = os.path.join(BASE_DIR, "memory.sqlite")
CHROMA_DIR = os.path.join(BASE_DIR, "chroma")

# Playwright MCP Configuration
# Set to True to use Chrome Extension mode (connects to user's browser)
# Set to False to use stdio mode (launches separate browser)
USE_CHROME_EXTENSION = os.getenv("USE_CHROME_EXTENSION", "false").lower() == "true"
# WebSocket endpoint from Chrome Extension (default: ws://localhost:9223/extension)
CHROME_EXTENSION_WS_URL = os.getenv("CHROME_EXTENSION_WS_URL", "ws://localhost:9223/extension")

# ===== Vector Store (long-term, cross-thread) =====
from langchain_chroma import Chroma
emb = OpenAIEmbeddings()  # requires OPENAI_API_KEY in env
vstore = Chroma(collection_name="memories", embedding_function=emb, persist_directory=CHROMA_DIR)

def ns_user(user_id: str) -> str:
    return f"user::{user_id}"

def add_memories(user_id: str, docs: List[str], metadata: dict):
    if not docs:
        return
    metadatas = [{**metadata, "ns": ns_user(user_id)} for _ in docs]
    vstore.add_texts(docs, metadatas=metadatas)

def search_memories(user_id: str, query: str, k: int = TOP_K) -> List[str]:
    if not query.strip():
        return []
    results = vstore.similarity_search(query, k=k, filter={"ns": ns_user(user_id)})
    return [r.page_content for r in results]

# ===== LangGraph State =====
class ChatState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]

# Chat model (OpenAI)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def reply_node(state: ChatState, *, user_id: str) -> ChatState:
    window = state["messages"][-WINDOW:]
    last_user = next((m for m in reversed(window) if m.type == "human"), None)
    query = last_user.content if last_user else ""
    long_term = search_memories(user_id, query, k=TOP_K)

    sys = [SystemMessage(content="You are a concise, helpful assistant.")]
    if long_term:
        sys.append(SystemMessage(content="Relevant long-term context:\n- " + "\n- ".join(long_term)))

    ai = llm.invoke(sys + window)
    return {"messages": [AIMessage(content=ai.content)]}

# ===== MCP node (OpenAI tools agent) =====
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent

# Global MCP client to maintain persistent connection across tool calls
_mcp_client = None
_mcp_tools = None

async def get_mcp_client_and_tools():
    """Get or create persistent MCP client and tools"""
    global _mcp_client, _mcp_tools
    
    if _mcp_client is None or _mcp_tools is None:
        # Configure MCP server based on mode
        if USE_CHROME_EXTENSION:
            # Chrome Extension mode: Playwright MCP connects to Chrome Extension via CDP
            # The Chrome Extension must be installed and running
            # Use --extension flag to connect to running browser extension
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": [
                        "-y", 
                        "@playwright/mcp",
                        "--extension"
                    ],
                    "env": {
                        "PLAYWRIGHT_MCP_EXTENSION_TOKEN": "XzBiEfI8PhLZYGXTlCMgrmjin_7tX8N1OCA_a5nXHIs"
                    }
                }
            }
        else:
            # Stdio mode: Launch separate browser instance (default)
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp"],  
                }
            }
        
        _mcp_client = MultiServerMCPClient(connections=servers)
        _mcp_tools = await _mcp_client.get_tools()
        print(f"[DEBUG] Created new MCP client with {len(_mcp_tools)} tools")
    
    return _mcp_client, _mcp_tools

async def mcp_node(state: ChatState) -> ChatState:
    """
    MCP node that uses Playwright for browser automation.
    Supports two modes:
    1. Chrome Extension mode: Connects to user's Chrome browser via CDP (preserves session)
    2. Stdio mode: Launches separate browser instance (no session)
    """
    last_user = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    user_text = (last_user.content if last_user else "").strip()
    if not user_text:
        return {"messages": [AIMessage(content="(no user message to act on)")]}
    
    tools_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Get persistent MCP client and tools (reuses connection across calls)
    client, tools = await get_mcp_client_and_tools()
    
    # Debug: Log available tools
    print(f"\n[DEBUG] Available MCP tools: {[tool.name for tool in tools]}\n")
    
    # Debug: Show snapshot tool details if available
    snapshot_tool = next((t for t in tools if "snapshot" in t.name.lower() or "capture" in t.name.lower()), None)
    if snapshot_tool:
        print(f"[DEBUG] Snapshot tool found: {snapshot_tool.name}")
        print(f"[DEBUG] Snapshot tool description: {snapshot_tool.description[:200]}...")

    # Use langchain 1.0+ create_agent API
    # Enhanced system prompt to ensure proper Playwright workflow
    agent = create_agent(
        model=tools_llm,
        tools=tools,
        system_prompt="""You are a browser automation assistant using Playwright MCP.

CRITICAL WORKFLOW - FOLLOW EXACTLY:
1. Navigate to a page using browser_navigate
2. ALWAYS call browser_snapshot IMMEDIATELY after navigation (in the same tool call batch if possible)
3. Wait for page load if needed using browser_wait_for BEFORE capturing snapshot
4. Analyze the snapshot returned by browser_snapshot to find elements
5. Use element references (ref) IMMEDIATELY after browser_snapshot - call browser_click right away

CRITICAL RULES ABOUT REFS AND TIMING:
- Element references (ref) are ONLY valid immediately after the browser_snapshot call
- You MUST call browser_click/browser_type/etc. IMMEDIATELY after browser_snapshot
- Do NOT wait or do other operations between browser_snapshot and browser_click
- Each browser_snapshot call generates NEW refs (e.g., e2, e3, e58)
- NEVER reuse refs from browser_navigate response - they are invalid
- ALWAYS find the element in the most recent browser_snapshot response
- Look for the element text/description in the snapshot YAML, then use its ref IMMEDIATELY

WORKFLOW (CRITICAL TIMING): 
1. Navigate → browser_navigate
2. Wait (if needed) → browser_wait_for
3. Capture → browser_snapshot (get fresh refs)
4. IMMEDIATELY Parse → Find element in snapshot YAML (look for "Sign in", "Log in", etc.)
5. IMMEDIATELY Extract → Get the ref from that element (e.g., ref=e58)
6. IMMEDIATELY Interact → Call browser_click with that ref RIGHT AWAY

TIMING IS CRITICAL: Call browser_click immediately after browser_snapshot returns. Do not delay."""
    )
    
    # Invoke the agent with streaming to see step-by-step execution
    try:
        print(f"\n[DEBUG] Starting agent execution for: {user_text}\n")
        
        # Use astream to see step-by-step execution and collect final result
        messages_so_far = [HumanMessage(content=user_text)]
        result = None
        async for chunk in agent.astream({"messages": messages_so_far}):
            # Log each step
            for key, value in chunk.items():
                if isinstance(value, dict) and "messages" in value:
                    for msg in value["messages"]:
                        msg_type = type(msg).__name__
                        print(f"[DEBUG] Step - {msg_type}:")
                        if hasattr(msg, 'content') and msg.content:
                            content_str = str(msg.content)
                            if len(content_str) > 300:
                                print(f"  Content: {content_str[:300]}...")
                            else:
                                print(f"  Content: {content_str}")
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            print(f"  Tool calls: {[tc.get('name', 'unknown') for tc in msg.tool_calls]}")
                            for tc in msg.tool_calls:
                                if 'args' in tc:
                                    print(f"    Args: {tc['args']}")
                        if hasattr(msg, 'tool_call_id'):
                            print(f"  Tool result (ID: {msg.tool_call_id})")
                            # If this is a browser_snapshot result, show the full snapshot
                            if hasattr(msg, 'content') and 'snapshot' in str(msg.content).lower():
                                content_str = str(msg.content)
                                # Extract and show the snapshot YAML
                                if 'Page Snapshot:' in content_str:
                                    snapshot_start = content_str.find('Page Snapshot:')
                                    snapshot_end = content_str.find('```', snapshot_start + 20)
                                    if snapshot_end == -1:
                                        snapshot_end = len(content_str)
                                    snapshot_section = content_str[snapshot_start:snapshot_end]
                                    print(f"  [SNAPSHOT] Full snapshot content:\n{snapshot_section}")
            # Keep the last chunk as result
            result = chunk
        
        # Debug: Log all messages to see what happened
        final_messages = result.get("messages", [])
        print(f"\n[DEBUG] Agent execution completed. Total messages: {len(final_messages)}")
        for i, msg in enumerate(final_messages):
            msg_type = type(msg).__name__
            print(f"[DEBUG] Final Message {i}: {msg_type}")
            if hasattr(msg, 'content'):
                content_str = str(msg.content)
                # Show first 500 chars for tool calls
                if len(content_str) > 500:
                    print(f"[DEBUG]   Content preview: {content_str[:500]}...")
                else:
                    print(f"[DEBUG]   Content: {content_str}")
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                print(f"[DEBUG]   Tool calls: {msg.tool_calls}")
        
        # Extract the final AI message
        final_ai_message = next((m for m in reversed(final_messages) if isinstance(m, AIMessage)), None)
        final_text = final_ai_message.content if final_ai_message else str(result)
        
        return {"messages": [AIMessage(content=final_text)]}
    except Exception as e:
        # Enhanced error handling with debugging info
        error_msg = str(e)
        print(f"\n[ERROR] MCP Node Error: {error_msg}")
        print(f"[ERROR] Exception type: {type(e).__name__}")
        
        # Try to get current page snapshot for debugging
        try:
            # Look for snapshot-related tools
            snapshot_tool = next((t for t in tools if "snapshot" in t.name.lower() or "capture" in t.name.lower()), None)
            if snapshot_tool:
                print(f"[DEBUG] Attempting to capture snapshot for debugging...")
                snapshot_result = await snapshot_tool.ainvoke({})
                snapshot_str = str(snapshot_result)
                print(f"[DEBUG] Snapshot captured ({len(snapshot_str)} chars)")
                print(f"[DEBUG] Snapshot preview (first 2000 chars):\n{snapshot_str[:2000]}...")
        except Exception as debug_error:
            print(f"[DEBUG] Could not capture snapshot: {debug_error}")
        
        return {"messages": [AIMessage(content=f"Error: {error_msg}. The agent may need to capture a page snapshot first before interacting with elements.")]}

def trim_node(state: ChatState) -> ChatState:
    return {"messages": state["messages"][-WINDOW:]}

# ===== Graph =====
builder = StateGraph(ChatState)

def reply_wrapped(state: ChatState, config) -> ChatState:
    uid = config["configurable"].get("user_id", "anon")
    return reply_node(state, user_id=uid)

# Add all nodes
builder.add_node("reply", reply_wrapped)
builder.add_node("trim", trim_node)
builder.add_node("mcp", mcp_node)  # MCP node for browser automation

# Create a router node to decide: use MCP for browser tasks, regular chat otherwise
def route_node(state: ChatState) -> ChatState:
    """Router node - doesn't modify state, just passes through"""
    return state

def route_message(state: ChatState) -> str:
    """Route to MCP if message suggests browser automation, otherwise regular chat"""
    last_user = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    if not last_user:
        return "reply"
    
    user_text = last_user.content.lower()
    # Keywords that suggest browser automation tasks
    browser_keywords = [
        "click", "navigate", "browser", "page", "website", "web", 
        "screenshot", "scrape", "automate", "interact", "button", 
        "form", "fill", "submit", "pull request", "github", "make a pr"
    ]
    
    if any(keyword in user_text for keyword in browser_keywords):
        return "mcp"
    return "reply"

# Add router node
builder.add_node("route", route_node)

# Set up routing - START -> route -> (mcp or reply) -> trim -> END
builder.set_entry_point("route")
builder.add_conditional_edges(
    "route",
    route_message,
    {
        "mcp": "mcp",
        "reply": "reply"
    }
)
builder.add_edge("mcp", "trim")  # MCP -> trim -> END
builder.add_edge("reply", "trim")  # Reply -> trim -> END
builder.add_edge("trim", END)

# Initialize checkpointer and graph (will be set up in lifespan)
checkpointer = None
graph = None

# ===== API =====
class ChatIn(BaseModel):
    user_id: str
    thread_id: str
    message: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage async checkpointer lifecycle"""
    global checkpointer, graph
    # Enter async context manager for checkpointer
    async with AsyncSqliteSaver.from_conn_string(SQLITE_URL) as cp:
        checkpointer = cp
        graph = builder.compile(checkpointer=checkpointer)
        yield  # App runs here
    # Context manager exits here (cleanup)

app = FastAPI(lifespan=lifespan)

@app.post("/chat")
async def chat(inp: ChatIn):
    # Use ainvoke for async graph execution (required for async nodes like mcp_node)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=inp.message)]},
        config={"configurable": {"thread_id": inp.thread_id, "user_id": inp.user_id}},
    )

    reply = [m for m in result["messages"] if isinstance(m, AIMessage)][-1].content

    add_memories(
        user_id=inp.user_id,
        docs=[f"User said: {inp.message}", f"Assistant replied: {reply}"],
        metadata={"kind": "chat", "thread_id": inp.thread_id},
    )
    return {"reply": reply}

@app.post("/debug/mcp-snapshot")
async def debug_mcp_snapshot():
    """Debug endpoint to capture and return current page snapshot"""
    try:
        # Configure MCP server (use same config as mcp_node)
        if USE_CHROME_EXTENSION:
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp", "--extension"],
                    "env": {
                        "PLAYWRIGHT_MCP_EXTENSION_TOKEN": os.getenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "")
                    }
                }
            }
        else:
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp"],
                }
            }
        
        client = MultiServerMCPClient(connections=servers)
        tools = await client.get_tools()
        
        # Find snapshot tool
        snapshot_tool = next((t for t in tools if "snapshot" in t.name.lower() or "capture" in t.name.lower()), None)
        
        if not snapshot_tool:
            return {
                "error": "No snapshot tool found",
                "available_tools": [t.name for t in tools]
            }
        
        # Capture snapshot (tools can be called directly without session context)
        snapshot_result = await snapshot_tool.ainvoke({})
        
        snapshot_str = str(snapshot_result)
        return {
            "success": True,
            "snapshot": snapshot_str,
            "snapshot_length": len(snapshot_str),
            "tool_used": snapshot_tool.name
        }
    except Exception as e:
        return {
            "error": str(e),
            "error_type": type(e).__name__
        }

# Run: uvicorn main:app --reload
