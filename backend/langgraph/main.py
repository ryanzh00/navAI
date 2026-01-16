# pip install fastapi uvicorn langgraph langchain langchain-openai langchain-community chromadb tiktoken langchain-mcp-adapters python-dotenv langchain-chroma

import os
import asyncio
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware


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
import openai

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
if os.name == "nt":
    # Windows: use npx from PATH, or override via NPM_BIN
    NPM = os.getenv("NPM_BIN", "npx")
else:
    # macOS/Homebrew default (you can still override via NPM_BIN)
    NPM = os.getenv("NPM_BIN", "/opt/homebrew/bin/npx")

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
    try:
        results = vstore.similarity_search(query, k=k, filter={"ns": ns_user(user_id)})
        return [r.page_content for r in results]
    except (openai.RateLimitError, openai.APIError, Exception) as e:
        # Gracefully handle OpenAI API errors (quota, rate limits, etc.)
        # Return empty list to allow the backend to continue functioning without memory search
        print(f"Warning: Memory search failed: {e}")
        return []

# ===== LangGraph State =====
class ChatState(TypedDict, total=False):
    messages: Annotated[List[AnyMessage], add_messages]
    execution_plan: str  # Optional: stores the planned steps
    goal_achieved: bool  # Whether the user's goal has been achieved

# Chat model (OpenAI)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def reply_node(state: ChatState, *, user_id: str, page_content: dict | None = None) -> ChatState:
    window = state["messages"][-WINDOW:]
    last_user = next((m for m in reversed(window) if m.type == "human"), None)
    query = last_user.content if last_user else ""
    long_term = search_memories(user_id, query, k=TOP_K)

    sys = [SystemMessage(content="You are a concise, helpful assistant. Keep your replies short, easy to understand, and conversational. Avoid technical jargon.")]
    
    # Add long-term memory context if available
    if long_term:
        sys.append(SystemMessage(content="Relevant long-term context:\n- " + "\n- ".join(long_term)))
    
    # Add page content as context if available (for non-agentic mode)
    if page_content:
        page_text = page_content.get("text", "")[:3000]  # Limit to 3000 chars
        page_title = page_content.get("title", "")
        page_url = page_content.get("url", "")
        headings = page_content.get("headings", [])[:10]  # Limit to 10 headings
        
        page_context = f"Current page context:\n"
        page_context += f"URL: {page_url}\n"
        page_context += f"Title: {page_title}\n"
        if headings:
            page_context += f"Headings: {', '.join(headings)}\n"
        if page_text:
            page_context += f"Content preview: {page_text}\n"
        page_context += "\nUse this page context to answer the user's question. Reference specific content from the page when relevant."
        
        sys.append(SystemMessage(content=page_context))

    ai = llm.invoke(sys + window[:-1] + [HumanMessage(content=query)] if query else sys + window)
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

def enhance_user_intent(user_text: str) -> str:
    """
    Enhance user intent with better context and clarity.
    Breaks down high-level goals into actionable steps.
    """
    enhancer_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    enhancement_prompt = f"""User said: "{user_text}"

Interpret this as a browser automation task. Clarify:
1. What is the ultimate goal?
2. What are the implicit steps needed?
3. What should the final state look like?

Examples:
- User: "find pictures of dogs"
  → Goal: Display image search results for "dogs"
  → Steps: [Find search bar] → [Type "dogs"] → [Click search] → [Click Images tab]
  → Final state: Image grid showing dog pictures

- User: "buy a red shirt"
  → Goal: Add a red shirt to shopping cart
  → Steps: [Find search] → [Type "red shirt"] → [Click search] → [Click first result] → [Add to cart]
  → Final state: Item in cart with confirmation

- User: "login to my account"
  → Goal: Successfully authenticate user
  → Steps: [Find login link/button] → [Click it] → [Find username field] → [Type username] → [Find password field] → [Type password] → [Click login button]
  → Final state: User logged in (check for profile/account indicator)

Now interpret: "{user_text}"

Provide a clear, step-by-step plan in natural language that the browser automation can follow.
"""
    
    try:
        enhanced = enhancer_llm.invoke([HumanMessage(content=enhancement_prompt)])
        return enhanced.content
    except Exception as e:
        print(f"[WARNING] Intent enhancement failed: {e}, using original text")
        return user_text

def plan_task(user_text: str) -> str:
    """
    Break down user intent into specific, actionable steps.
    """
    planner_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    
    planning_prompt = f"""Given this user request: "{user_text}"

Break it down into 3-7 specific, actionable steps. Each step should be:
- Clear and specific
- In logical order
- Achievable with browser automation tools (click, type, navigate, wait, etc.)

Format as a numbered list. Example:
User: "find pictures of dogs"
Steps:
1. Take a snapshot of the current page to see what's available
2. Locate the search input field (look for search box, search bar, or input with placeholder "Search")
3. Type "dogs" into the search field
4. Click the search button or press Enter to submit
5. Wait for search results to load and take a new snapshot
6. Locate and click the "Images" tab, link, or filter button
7. Verify that image results are displayed

Now plan the steps for: "{user_text}"
"""
    
    try:
        plan = planner_llm.invoke([HumanMessage(content=planning_prompt)])
        return plan.content
    except Exception as e:
        print(f"[WARNING] Task planning failed: {e}")
        return f"1. Take a snapshot\n2. Complete the task: {user_text}"

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

    # Enhance user intent to understand the goal better
    enhanced_intent = enhance_user_intent(user_text)
    print(f"[DEBUG] Enhanced intent: {enhanced_intent}")
    
    # Get execution plan if available, otherwise create one
    execution_plan = state.get("execution_plan", "")
    if not execution_plan:
        execution_plan = plan_task(user_text)
        print(f"[DEBUG] Created execution plan:\n{execution_plan}")

    # Build the instruction with plan context
    instruction = f"""Goal: {enhanced_intent}

Execution Plan:
{execution_plan}

Now execute this plan step by step. After each major action, verify progress toward the goal."""
    
    tools_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Enhanced system prompt with intelligent reasoning
    agent = create_agent(
        model=tools_llm,
        tools=_mcp_tools,
        system_prompt="""You are an intelligent browser automation assistant using Playwright MCP.

CORE PRINCIPLES:
1. UNDERSTAND INTENT: Break down user requests into clear, actionable steps
   - "find pictures of dogs" → [1] Find search bar, [2] Type "dogs", [3] Click search, [4] Click "Images" tab/filter
   - "buy a red shirt" → [1] Find search, [2] Type "red shirt", [3] Click search, [4] Click first result, [5] Add to cart
   
2. ELEMENT DISCOVERY STRATEGY (in priority order):
   - Search by visible text/label (most reliable)
   - Search by ARIA role (button, searchbox, link, etc.)
   - Search by semantic HTML (input[type="search"], button, a[href])
   - Search by placeholder text
   - Search by nearby text context
   
3. WORKFLOW PATTERN:
   a) ALWAYS start with browser_snapshot to see current page state
   b) Analyze the snapshot to understand page structure
   c) Identify target elements using multiple strategies
   d) Execute actions (click, type, etc.)
   e) Wait for page changes, then snapshot again
   f) Verify the action succeeded before proceeding
   
4. ERROR RECOVERY:
   - If element not found, try alternative selectors/strategies
   - If action fails, wait longer and retry
   - If page seems stuck, take a new snapshot
   - If goal unclear, break it into smaller sub-tasks
   
5. VALIDATION:
   - After each major action, verify the result matches the goal
   - Check if page content changed as expected
   - Confirm you're making progress toward the user's goal
   
6. COMMUNICATION:
   - Explain what you're doing in simple terms
   - Report progress: "Found the search bar", "Typing 'dogs'", "Clicking Images tab"
   - If stuck, explain what you're trying and why

RULES:
- ALWAYS call browser_snapshot right before interacting so refs are fresh.
- Immediately use refs from the most recent browser_snapshot with browser_click/browser_type.
- Do not reuse old refs after a new snapshot.
- Do not reload the page unless explicitly asked to navigate.
- If the page URL is about:blank or there are no open pages, call browser_navigate first.

Remember: Think step-by-step, verify each action, and always use fresh snapshots before interacting."""
    )

    # Execute and stream logs to server stdout (optional)
    try:
        print(f"\n[DEBUG] Starting agent execution for: {user_text}\n")
        print(f"[DEBUG] Execution plan:\n{execution_plan}\n")
        messages_so_far = [HumanMessage(content=instruction)]
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
        
        # Extract text content, handling both string and dict responses
        if final_ai_message:
            content = final_ai_message.content
            # If content is a dict (raw model response), extract the actual message text
            if isinstance(content, dict):
                # Try to extract message content from various possible structures
                if 'model' in content and 'messages' in content['model']:
                    messages = content['model']['messages']
                    if messages:
                        # Handle both dict and AIMessage objects
                        first_msg = messages[0]
                        if isinstance(first_msg, AIMessage):
                            final_text = first_msg.content
                        elif isinstance(first_msg, dict) and 'content' in first_msg:
                            final_text = first_msg['content']
                        else:
                            final_text = str(first_msg)
                    else:
                        final_text = str(content)
                elif 'content' in content:
                    final_text = content['content']
                else:
                    final_text = str(content)
            elif isinstance(content, str):
                final_text = content
            else:
                final_text = str(content)
        else:
            final_text = "No response generated"
        
        # Check for errors in tool results
        tool_results = [m for m in final_messages if hasattr(m, 'tool_call_id') and hasattr(m, 'content')]
        has_errors = False
        error_details = []
        
        for tool_result in tool_results:
            result_content = str(tool_result.content) if hasattr(tool_result, 'content') else ""
            # Check for common error indicators
            if any(indicator in result_content.lower() for indicator in ['error', 'failed', 'exception', 'timeout', 'not found', 'could not']):
                has_errors = True
                if result_content:
                    error_details.append(result_content[:200])  # Limit error detail length
        
        # Build the response message
        if has_errors:
            # Add error information to the response
            error_summary = "\n\n⚠️ Task encountered some issues. " + (error_details[0] if error_details else "Please check the browser window for details.")
            response_text = final_text + error_summary
        else:
            # Add success confirmation
            success_confirmation = "\n\n✅ Task completed successfully!"
            response_text = final_text + success_confirmation
        
        return {"messages": [AIMessage(content=response_text)]}

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"\n[ERROR] MCP Node Error: {error_msg}")
        print(f"[ERROR] Exception type: {error_type}")

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

        # Create user-friendly error message
        if "timeout" in error_msg.lower():
            friendly_error = "⛔ Task timed out. The browser operation took too long to complete. Please try again or check if the page is loading correctly."
        elif "not found" in error_msg.lower() or "could not find" in error_msg.lower():
            friendly_error = f"⛔ Could not find the requested element on the page. {error_msg[:200]}"
        elif "connection" in error_msg.lower() or "network" in error_msg.lower():
            friendly_error = "⛔ Network error occurred. Please check your internet connection and try again."
        else:
            # Generic error message
            friendly_error = f"⛔ Task failed: {error_msg[:300]}"
            if len(error_msg) > 300:
                friendly_error += "..."
        
        return {"messages": [AIMessage(content=friendly_error)]}

def plan_task_node(state: ChatState) -> ChatState:
    """
    Planning node: Break down user intent into actionable steps before execution.
    """
    last_user = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    if not last_user:
        return state
    
    user_text = last_user.content.strip()
    if not user_text:
        return state
    
    # Create execution plan
    execution_plan = plan_task(user_text)
    
    # Add plan to state
    plan_message = SystemMessage(content=f"Execution Plan:\n{execution_plan}")
    
    return {
        "messages": state["messages"] + [plan_message],
        "execution_plan": execution_plan,
        "goal_achieved": False
    }

def validate_node(state: ChatState) -> ChatState:
    """
    Validation node: Check if the goal has been achieved.
    For now, we'll mark it as achieved if no errors occurred.
    In the future, this could analyze the final page state.
    """
    # Check for errors in the last messages
    recent_messages = state["messages"][-5:]  # Check last 5 messages
    has_errors = False
    
    for msg in recent_messages:
        if isinstance(msg, AIMessage):
            content = str(msg.content).lower()
            if any(indicator in content for indicator in ['error', 'failed', 'could not', 'not found', 'timeout']):
                has_errors = True
                break
    
    goal_achieved = not has_errors
    
    return {
        "goal_achieved": goal_achieved
    }

def trim_node(state: ChatState) -> ChatState:
    return {"messages": state["messages"][-WINDOW:]}

# ===== Graph =====
builder = StateGraph(ChatState)

def reply_wrapped(state: ChatState, config) -> ChatState:
    uid = config["configurable"].get("user_id", "anon")
    page_content = config["configurable"].get("page_content", None)
    return reply_node(state, user_id=uid, page_content=page_content)

# Add all nodes
builder.add_node("reply", reply_wrapped)
builder.add_node("trim", trim_node)
builder.add_node("mcp", mcp_node)  # MCP node for browser automation
builder.add_node("plan", plan_task_node)  # Planning node for task decomposition
builder.add_node("validate", validate_node)  # Validation node to check goal achievement

# Create a router node to decide: use MCP for browser tasks, regular chat otherwise
def route_node(state: ChatState) -> ChatState:
    """Router node - doesn't modify state, just passes through"""
    return state

def route_message(state: ChatState, config=None) -> str:
    """Route to MCP if agentic_mode is enabled, otherwise regular chat"""
    # Always check agentic_mode first - this is the primary routing mechanism
    agentic_mode = False
    if config and "configurable" in config:
        agentic_mode = config["configurable"].get("agentic_mode", False)
    
    # If agentic_mode is explicitly set (True or False), use it
    # This ensures the toggle always controls routing
    if agentic_mode:
        print(f"[DEBUG] Routing to MCP (agentic_mode=True)")
        return "mcp"
    else:
        print(f"[DEBUG] Routing to reply (agentic_mode=False)")
        return "reply"

# Add router node
builder.add_node("route", route_node)

# Set up routing - START -> route -> (plan -> mcp or reply) -> validate -> trim -> END
builder.set_entry_point("route")
builder.add_conditional_edges(
    "route",
    route_message,
    {
        "mcp": "plan",  # For agentic mode: plan first, then execute
        "reply": "reply"  # For non-agentic mode: direct to reply
    }
)
# Planning -> MCP execution -> Validation -> Trim
builder.add_edge("plan", "mcp")
builder.add_edge("mcp", "validate")
builder.add_edge("validate", "trim")
# Direct path for non-agentic mode
builder.add_edge("reply", "trim")
builder.add_edge("trim", END)

# Initialize checkpointer and graph (will be set up in lifespan)
checkpointer = None
graph = None

# ===== API =====
class PageContentData(BaseModel):
    url: str
    title: str
    text: str
    headings: List[str]

class ChatIn(BaseModel):
    user_id: str
    thread_id: str  # kept for your external caller's tracking; we don't spawn per-thread browsers in this file
    message: str
    agentic_mode: bool = False  # Whether to use agentic mode (MCP tools)
    page_content: PageContentData | None = None  # Page content for context in non-agentic mode

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",       # allow extensions (dev)
        "http://localhost:3000",      # if you ever have a dev UI
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",      # optional
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

    # Log the agentic_mode setting for debugging
    print(f"[DEBUG] Chat request - agentic_mode: {inp.agentic_mode}, message: {inp.message[:50]}...")
    if inp.page_content:
        print(f"[DEBUG] Page content provided - URL: {inp.page_content.url}, Title: {inp.page_content.title}")

    # Prepare config with page content for non-agentic mode
    config_data = {
        "thread_id": inp.thread_id,
        "user_id": inp.user_id,
        "agentic_mode": inp.agentic_mode
    }
    
    # Add page content to config if provided (for non-agentic mode)
    if inp.page_content:
        config_data["page_content"] = {
            "url": inp.page_content.url,
            "title": inp.page_content.title,
            "text": inp.page_content.text,
            "headings": inp.page_content.headings
        }

    # Use ainvoke for async graph execution (required for async nodes like mcp_node)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=inp.message)]},
        config={"configurable": config_data},
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