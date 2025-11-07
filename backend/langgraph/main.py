# pip install fastapi uvicorn langgraph langchain langchain-openai langchain-community chromadb tiktoken langchain-mcp-adapters python-dotenv langchain-chroma

import os
import asyncio
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# Load environment variables from .env file
load_dotenv()

from typing import List, TypedDict
from typing_extensions import Annotated
from fastapi import FastAPI, HTTPException
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
NPM = os.getenv("NPM_BIN", "/opt/homebrew/bin/npx")  # adjust if needed

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
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent

# Global, long-lived MCP client and tools (keep them alive for the whole app lifetime)
_mcp_client: MultiServerMCPClient | None = None
_mcp_session = None
_mcp_tools = None

async def get_mcp_client_and_tools():
    """
    Return the cached MCP client and tools.
    They are initialized in the lifespan context.
    """
    global _mcp_client, _mcp_tools
    if _mcp_client is None or _mcp_tools is None:
        raise RuntimeError("MCP client not initialized. Application startup may have failed.")
    return _mcp_client, _mcp_tools

async def navigate_to_home():
    """
    Navigate the headed Playwright MCP browser to https://www.google.com.
    Requires MCP client to have been initialized.
    """
    global _mcp_tools
    # Ensure MCP tools exist
    if not _mcp_tools:
        raise RuntimeError("MCP tools not available")

    # Find the browser_navigate tool
    nav_tool = next((t for t in _mcp_tools if "browser_navigate" in t.name.lower()), None)
    if not nav_tool:
        raise RuntimeError(f"browser_navigate tool not found. Available tools: {[t.name for t in _mcp_tools]}")

    # Invoke navigation
    result = await nav_tool.ainvoke({"url": "https://www.google.com"})
    print("[DEBUG] Navigated to Google.com via MCP")
    return result

async def keep_mcp_alive():
    """Periodically interact with MCP to keep the subprocess alive"""
    global _mcp_tools
    while True:
        try:
            await asyncio.sleep(30)  # Every 30 seconds
            # Try to list tabs to keep connection active
            list_tool = next((t for t in _mcp_tools if "tabs" in t.name.lower()), None)
            if list_tool:
                result = await list_tool.ainvoke({})
                print(f"[DEBUG] Keep-alive ping sent, got: {len(str(result))} chars")
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[DEBUG] Keep-alive error (continuing): {e}")

async def mcp_node(state: ChatState) -> ChatState:
    """
    MCP node that uses Playwright for browser automation (headed).
    Uses a persistent MCP client so the window remains open between calls.
    """
    global _mcp_client, _mcp_tools
    
    # Get user text
    last_user = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    user_text = (last_user.content if last_user else "").strip()
    if not user_text:
        return {"messages": [AIMessage(content="(no user message to act on)")]}

    tools_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Enhanced system prompt to ensure proper Playwright workflow
    agent = create_agent(
        model=tools_llm,
        tools=_mcp_tools,
        system_prompt="""You are a browser automation assistant using Playwright MCP.

RULES:
- If there are no open pages or the URL is about:blank, call browser_navigate first.
- After any navigation, call browser_wait_for (time=3000ms) before snapshot.
- ALWAYS call browser_snapshot right before interacting so refs are fresh.
- Immediately use refs from the most recent browser_snapshot with browser_click/browser_type.
- Do not reuse old refs after a new snapshot.

TYPICAL PLAN:
1) browser_tabs list → optionally select a tab
2) (if needed) browser_navigate
3) browser_wait_for (3000)
4) browser_snapshot
5) Interact using refs (browser_click, browser_type, etc.)
6) If page changes, repeat wait → snapshot → interact.
"""
    )

    # Execute and stream logs to server stdout (optional)
    try:
        print(f"\n[DEBUG] Starting agent execution for: {user_text}\n")
        messages_so_far = [HumanMessage(content=user_text)]
        result = None
        async for chunk in agent.astream({"messages": messages_so_far}):
            for key, value in chunk.items():
                if isinstance(value, dict) and "messages" in value:
                    for msg in value["messages"]:
                        msg_type = type(msg).__name__
                        print(f"[DEBUG] Step - {msg_type}:")
                        if hasattr(msg, 'content') and msg.content:
                            content_str = str(msg.content)
                            print("  Content:", (content_str[:300] + "...") if len(content_str) > 300 else content_str)
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            print(f"  Tool calls: {[tc.get('name', 'unknown') for tc in msg.tool_calls]}")
                            for tc in msg.tool_calls:
                                if 'args' in tc:
                                    print(f"    Args: {tc['args']}")
                        if hasattr(msg, 'tool_call_id'):
                            print(f"  Tool result (ID: {msg.tool_call_id})")
            result = chunk

        final_messages = result.get("messages", [])
        print(f"\n[DEBUG] Agent execution completed. Total messages: {len(final_messages)}")
        final_ai_message = next((m for m in reversed(final_messages) if isinstance(m, AIMessage)), None)
        final_text = final_ai_message.content if final_ai_message else str(result)
        return {"messages": [AIMessage(content=final_text)]}

    except Exception as e:
        error_msg = str(e)
        print(f"\n[ERROR] MCP Node Error: {error_msg}")
        print(f"[ERROR] Exception type: {type(e).__name__}")

        # Try to snapshot current page for debugging
        try:
            snapshot_tool = next((t for t in _mcp_tools if "snapshot" in t.name.lower() or "capture" in t.name.lower()), None)
            if snapshot_tool:
                print(f"[DEBUG] Attempting to capture snapshot for debugging...")
                snapshot_result = await snapshot_tool.ainvoke({})
                snapshot_str = str(snapshot_result)
                print(f"[DEBUG] Snapshot captured ({len(snapshot_str)} chars)")
                print(f"[DEBUG] Snapshot preview (first 1500 chars):\n{snapshot_str[:1500]}...")
        except Exception as debug_error:
            print(f"[DEBUG] Could not capture snapshot: {debug_error}")

        return {"messages": [AIMessage(content=f"Error: {error_msg}")]}

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
        "form", "fill", "submit", "pull request", "github", "make a pr",
        "login", "logout", "type", "select", "tab", "snapshot"
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
builder.add_edge("mcp", "trim")   # MCP -> trim -> END
builder.add_edge("reply", "trim") # Reply -> trim -> END
builder.add_edge("trim", END)

# Initialize checkpointer and graph (will be set up in lifespan)
checkpointer = None
graph = None

# ===== API =====
class ChatIn(BaseModel):
    user_id: str
    thread_id: str  # kept for your external caller's tracking; we don't spawn per-thread browsers in this file
    message: str

class OpenIn(BaseModel):
    url: str | None = "https://github.com"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage async checkpointer lifecycle and hold MCP client for the whole app lifetime."""
    global checkpointer, graph, _mcp_client, _mcp_session, _mcp_tools
    
    async with AsyncSqliteSaver.from_conn_string(SQLITE_URL) as cp:
        checkpointer = cp
        
        # Create MCP client
        servers = {
            "playwright": {
                "transport": "stdio",
                "command": NPM,
                "args": ["-y", "@playwright/mcp@latest", "--user-data-dir=./mcp_data"],
            }
        }
        _mcp_client = MultiServerMCPClient(connections=servers)
        print("[DEBUG] Created MCP client")
        
        # Use session context to keep connection alive
        async with _mcp_client.session("playwright") as session:
            _mcp_session = session
            # Load tools from session
            _mcp_tools = await load_mcp_tools(session)
            print(f"[DEBUG] Loaded {len(_mcp_tools)} tools from session")
            
            # Navigate to home to open browser window
            await navigate_to_home()

            graph = builder.compile(checkpointer=checkpointer)
            
            yield  # App runs here - browser stays open
        
        
        # Session closes here, browser will close

app = FastAPI(lifespan=lifespan)

@app.post("/open")
async def open_browser():
    try:
        # Browser is already open from lifespan - just navigate again if needed
        await navigate_to_home()
        return {"ok": True, "message": f"Headed browser is ready and showing Google."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat(inp: ChatIn):
    # Ensure MCP is alive
    await get_mcp_client_and_tools()

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
    """Debug endpoint to capture and return current page snapshot."""
    try:
        await get_mcp_client_and_tools()
        # Find snapshot tool
        snapshot_tool = next((t for t in _mcp_tools if "snapshot" in t.name.lower() or "capture" in t.name.lower()), None)
        if not snapshot_tool:
            return {"error": "No snapshot tool found", "available_tools": [t.name for t in _mcp_tools]}

        # Capture snapshot
        snapshot_result = await snapshot_tool.ainvoke({})
        snapshot_str = str(snapshot_result)
        return {
            "success": True,
            "snapshot": snapshot_str,
            "snapshot_length": len(snapshot_str),
            "tool_used": snapshot_tool.name
        }
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

# Run locally:
# uvicorn main:app --host 127.0.0.1 --port 8000
# NOTE: Avoid `--reload` if you want the headed browser to persist between edits; reload restarts the parent process, which will close the MCP child and its browser.