# pip install fastapi uvicorn langgraph langchain langchain-openai langchain-community chromadb tiktoken langchain-mcp-adapters python-dotenv langchain-chroma aiosqlite

import os
import sys
import asyncio
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import aiosqlite
from datetime import datetime
from typing import Optional, Dict, Any

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


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
from langgraph.graph.message import add_messages

# ===== Config =====
WINDOW = 8
TOP_K = 4

def get_today_date_context(*, timezone_name: Optional[str] = None) -> str:
    """
    Return a short, human-friendly 'today' context string for the model.
    If a user timezone is available and ZoneInfo is supported, use it.
    """
    tz = None
    if timezone_name and ZoneInfo is not None:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = None

    now = datetime.now(tz=tz) if tz else datetime.now()
    # Example: "Wednesday, January 28, 2026"
    pretty = now.strftime("%A, %B %d, %Y")
    iso = now.date().isoformat()
    if timezone_name:
        return f"Today's date is {pretty} ({iso}). Timezone: {timezone_name}."
    return f"Today's date is {pretty} ({iso})."

# Get user data directory (cross-platform)
def get_user_data_dir() -> str:
    """Get user-writable data directory for storing state files."""
    # Allow override via environment variable
    if user_data_dir := os.getenv("NAVAI_DATA_DIR"):
        return user_data_dir
    
    # Platform-specific user data directories
    home = os.path.expanduser("~")
    if os.name == "nt":
        # Windows: %APPDATA%\navAI
        appdata = os.getenv("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return os.path.join(appdata, "navAI")
    elif sys.platform == "darwin":
        # macOS: ~/Library/Application Support/navAI
        return os.path.join(home, "Library", "Application Support", "navAI")
    else:
        # Linux: ~/.config/navAI or ~/.local/share/navAI
        xdg_data_home = os.getenv("XDG_DATA_HOME", os.path.join(home, ".local", "share"))
        return os.path.join(xdg_data_home, "navAI")

# Create user data directory if it doesn't exist
USER_DATA_DIR = get_user_data_dir()
try:
    os.makedirs(USER_DATA_DIR, exist_ok=True, mode=0o755)
    # Verify directory is writable
    test_file = os.path.join(USER_DATA_DIR, ".write_test")
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        print(f"[INFO] User data directory is writable: {USER_DATA_DIR}")
    except Exception as e:
        print(f"[WARNING] User data directory may not be writable: {e}")
except Exception as e:
    print(f"[ERROR] Failed to create user data directory: {e}")
    raise

# State file paths in user data directory
CHROMA_DIR = os.path.join(USER_DATA_DIR, "chroma")
MCP_DATA_DIR = os.path.join(USER_DATA_DIR, "mcp_data")
USER_DB_PATH = os.path.join(USER_DATA_DIR, "user_info.db")
INIT_SCRIPT_PATH = os.path.join(USER_DATA_DIR, "init-script.js")
# Create subdirectories
os.makedirs(CHROMA_DIR, exist_ok=True, mode=0o755)
os.makedirs(MCP_DATA_DIR, exist_ok=True, mode=0o755)
print(f"[INFO] User data directory: {USER_DATA_DIR}")
print(f"[INFO] ChromaDB directory: {CHROMA_DIR}")
print(f"[INFO] MCP data directory: {MCP_DATA_DIR}")
print(f"[INFO] User database: {USER_DB_PATH}")
print("[DEBUG] size:", os.path.getsize(os.path.abspath(INIT_SCRIPT_PATH)) if os.path.exists(os.path.abspath(INIT_SCRIPT_PATH)) else None)


if os.name == "nt":
    # Windows: use npx from PATH, or override via NPM_BIN
    NPM = os.getenv("NPM_BIN", "npx")
else:
    # macOS/Homebrew default (you can still override via NPM_BIN)
    NPM = os.getenv("NPM_BIN", "/opt/homebrew/bin/npx")

# ===== User Database (SQLite) =====
_user_db: Optional[aiosqlite.Connection] = None

async def init_user_db():
    """Initialize SQLite database for user information."""
    global _user_db
    _user_db = await aiosqlite.connect(USER_DB_PATH)
    _user_db.row_factory = aiosqlite.Row  # Enable column access by name
    
    # Create user_info table if it doesn't exist
    await _user_db.execute("""
        CREATE TABLE IF NOT EXISTS user_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            date_of_birth DATE,
            email TEXT,
            phone TEXT,
            address TEXT,
            city TEXT,
            state TEXT,
            zip_code TEXT,
            country TEXT,
            timezone TEXT,
            additional_info TEXT,  -- Additional information about the user
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await _user_db.commit()
    print(f"[INFO] User database initialized: {USER_DB_PATH}")

async def close_user_db():
    """Close user database connection."""
    global _user_db
    if _user_db:
        await _user_db.close()
        _user_db = None

async def get_user_info() -> Dict[str, Any]:
    """Get user information from database (source of truth)."""
    if not _user_db:
        return {}
    
    async with _user_db.execute("SELECT * FROM user_info ORDER BY id DESC LIMIT 1") as cursor:
        row = await cursor.fetchone()
        if row:
            return {
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "date_of_birth": row["date_of_birth"],
                "email": row["email"],
                "phone": row["phone"],
                "address": row["address"],
                "city": row["city"],
                "state": row["state"],
                "zip_code": row["zip_code"],
                "country": row["country"],
                "timezone": row["timezone"],
                "additional_info": row["additional_info"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }
        return {}

async def update_user_info(info: Dict[str, Any]):
    """Update user information in database."""
    if not _user_db:
        return
    
    # Check if record exists
    async with _user_db.execute("SELECT COUNT(*) as count FROM user_info") as cursor:
        row = await cursor.fetchone()
        exists = row["count"] > 0 if row else False
    
    if exists:
        # Update existing record
        fields = []
        values = []
        for key, value in info.items():
            if key not in ["id", "created_at"]:  # Don't update these
                fields.append(f"{key} = ?")
                values.append(value)
        
        if fields:
            values.append(datetime.now().isoformat())  # updated_at
            values.append(1)  # WHERE id = 1 (assuming single user)
            await _user_db.execute(
                f"UPDATE user_info SET {', '.join(fields)}, updated_at = ? WHERE id = ?",
                values
            )
            await _user_db.commit()
    else:
        # Insert new record
        keys = list(info.keys())
        keys.append("updated_at")
        placeholders = ", ".join(["?"] * len(keys))
        keys_str = ", ".join(keys)
        values = [info.get(k) for k in info.keys()]
        values.append(datetime.now().isoformat())
        
        await _user_db.execute(
            f"INSERT INTO user_info ({keys_str}) VALUES ({placeholders})",
            values
        )
        await _user_db.commit()

# ===== Vector Store (long-term, cross-thread) =====
from langchain_chroma import Chroma
from typing import Optional

# emb = OpenAIEmbeddings()  # requires OPENAI_API_KEY in env
# vstore = Chroma(collection_name="memories", embedding_function=emb, persist_directory=CHROMA_DIR)
_vstore: Optional[Chroma] = None

def get_vstore() -> Optional[Chroma]:
    global _vstore

    if _vstore is not None:
        return _vstore

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[WARNING] OPENAI_API_KEY not set — vector memory disabled")
        return None

    emb = OpenAIEmbeddings()
    _vstore = Chroma(
        collection_name="memories",
        embedding_function=emb,
        persist_directory=CHROMA_DIR,
    )
    return _vstore

def add_memories(docs: List[str], metadata: dict = None):
    if not docs:
        return
    vstore = get_vstore()
    if vstore is None:
        return
    metadatas = [metadata or {} for _ in docs]
    vstore.add_texts(docs, metadatas=metadatas)

def search_memories(query: str, k: int = TOP_K) -> List[str]:
    if not query.strip():
        return []
    vstore = get_vstore()
    if vstore is None:
        return []
    try:
        results = vstore.similarity_search(query, k=k)
        return [r.page_content for r in results]
    except Exception as e:
        print(f"Warning: Memory search failed: {e}")
        return []

# ===== LangGraph State =====
class ChatState(TypedDict, total=False):
    messages: Annotated[List[AnyMessage], add_messages]
    execution_plan: str  # Optional: stores the planned steps
    goal_achieved: bool  # Whether the user's goal has been achieved

# Chat model (OpenAI)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

async def reply_node(state: ChatState, *, page_content: dict | None = None) -> ChatState:
    window = state["messages"][-WINDOW:]
    last_user = next((m for m in reversed(window) if m.type == "human"), None)
    query = last_user.content if last_user else ""
    long_term = search_memories(query, k=TOP_K)

    sys = [SystemMessage(content="You are a concise, helpful assistant. Keep your replies short, easy to understand, and conversational. Avoid technical jargon.")]
    
    # Add user information from database (source of truth)
    user_info = await get_user_info()
    sys.append(SystemMessage(content=get_today_date_context(timezone_name=(user_info.get("timezone") if user_info else None))))
    if user_info:
        user_context_parts = []
        if user_info.get("first_name"):
            user_context_parts.append(f"First name: {user_info['first_name']}")
        if user_info.get("last_name"):
            user_context_parts.append(f"Last name: {user_info['last_name']}")
        if user_info.get("date_of_birth"):
            user_context_parts.append(f"Date of birth: {user_info['date_of_birth']}")
        if user_info.get("email"):
            user_context_parts.append(f"Email: {user_info['email']}")
        if user_info.get("phone"):
            user_context_parts.append(f"Phone: {user_info['phone']}")
        if user_info.get("address"):
            addr_parts = [user_info.get("address", "")]
            if user_info.get("city"):
                addr_parts.append(user_info["city"])
            if user_info.get("state"):
                addr_parts.append(user_info["state"])
            if user_info.get("zip_code"):
                addr_parts.append(user_info["zip_code"])
            if user_info.get("country"):
                addr_parts.append(user_info["country"])
            user_context_parts.append(f"Address: {', '.join(filter(None, addr_parts))}")
        if user_info.get("timezone"):
            user_context_parts.append(f"Timezone: {user_info['timezone']}")
        if user_info.get("additional_info"):
            user_context_parts.append(f"Additional Information: {user_info['additional_info']}")
        
        if user_context_parts:
            sys.append(SystemMessage(content="User Information (source of truth):\n" + "\n".join(user_context_parts)))
    
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

async def mcp_node(state: ChatState, config=None) -> ChatState:
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
    
    # Get tab index from config if provided
    tab_index = None
    if config and "configurable" in config:
        tab_index = config["configurable"].get("tab_index")
    
    print(f"[DEBUG] MCP node - tab_index from config: {tab_index} (type: {type(tab_index)})")
    
    # Select the specified tab in Playwright browser if tab_index is provided
    if tab_index is not None:
        try:
            # Find the browser_tabs tool
            tabs_tool = next((t for t in _mcp_tools if "browser_tabs" in t.name.lower() or "tabs" in t.name.lower()), None)
            if tabs_tool:
                # First, list existing tabs to see what we have
                try:
                    list_result = await tabs_tool.ainvoke({"action": "list"})
                    print(f"[DEBUG] Current Playwright tabs: {list_result}")
                    # The result might be a string or dict, try to parse it
                    if isinstance(list_result, str):
                        # Try to count tabs from the result
                        import json
                        try:
                            tabs_data = json.loads(list_result)
                            num_tabs = len(tabs_data) if isinstance(tabs_data, list) else 1
                        except:
                            num_tabs = 1  # Assume at least 1 tab exists
                    else:
                        num_tabs = len(list_result) if isinstance(list_result, list) else 1
                    
                    print(f"[DEBUG] Found {num_tabs} tabs in Playwright browser, selecting tab {tab_index}")
                    
                    # If the tab doesn't exist, create tabs until we have enough
                    while tab_index >= num_tabs:
                        print(f"[DEBUG] Creating new tab (have {num_tabs}, need {tab_index + 1})")
                        await tabs_tool.ainvoke({"action": "create"})
                        num_tabs += 1
                    
                    # Now select the tab
                    print(f"[DEBUG] Selecting Playwright tab at index {tab_index}")
                    select_result = await tabs_tool.ainvoke({"action": "select", "index": tab_index})
                    print(f"[DEBUG] Successfully selected tab {tab_index}: {select_result}")
                except Exception as list_error:
                    print(f"[WARNING] Failed to list/create tabs, trying direct select: {list_error}")
                    # Try direct select anyway
                    await tabs_tool.ainvoke({"action": "select", "index": tab_index})
                    print(f"[DEBUG] Directly selected tab {tab_index}")
            else:
                print(f"[WARNING] browser_tabs tool not found. Available tools: {[t.name for t in _mcp_tools]}")
        except Exception as e:
            print(f"[WARNING] Failed to select tab {tab_index}: {e}")
            import traceback
            print(f"[WARNING] Traceback: {traceback.format_exc()}")
            # Continue anyway - might work with default tab

    # Get long-term memory context
    long_term = search_memories(user_text, k=TOP_K)
    
    # Get user information from database (source of truth)
    user_info = await get_user_info()
    
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

    # Build system prompt with user info and long-term memory context
    system_prompt_parts = ["""You are an intelligent browser automation assistant using Playwright MCP."""]
    system_prompt_parts.append(get_today_date_context(timezone_name=(user_info.get("timezone") if user_info else None)))
    
    # Add user information context if available
    if user_info:
        user_context_parts = []
        if user_info.get("first_name"):
            user_context_parts.append(f"First name: {user_info['first_name']}")
        if user_info.get("last_name"):
            user_context_parts.append(f"Last name: {user_info['last_name']}")
        if user_info.get("date_of_birth"):
            user_context_parts.append(f"Date of birth: {user_info['date_of_birth']}")
        if user_info.get("email"):
            user_context_parts.append(f"Email: {user_info['email']}")
        if user_info.get("phone"):
            user_context_parts.append(f"Phone: {user_info['phone']}")
        if user_info.get("address"):
            addr_parts = [user_info.get("address", "")]
            if user_info.get("city"):
                addr_parts.append(user_info["city"])
            if user_info.get("state"):
                addr_parts.append(user_info["state"])
            if user_info.get("zip_code"):
                addr_parts.append(user_info["zip_code"])
            if user_info.get("country"):
                addr_parts.append(user_info["country"])
            user_context_parts.append(f"Address: {', '.join(filter(None, addr_parts))}")
        if user_info.get("timezone"):
            user_context_parts.append(f"Timezone: {user_info['timezone']}")
        if user_info.get("additional_info"):
            user_context_parts.append(f"Additional Information: {user_info['additional_info']}")
        
        if user_context_parts:
            system_prompt_parts.append("\nUser Information (source of truth):")
            system_prompt_parts.append("\n".join(user_context_parts))
            system_prompt_parts.append("\nUse this information when filling forms, providing personal details, or customizing the experience.")
    
    # Add long-term memory context if available
    if long_term:
        system_prompt_parts.append("\nRelevant Long-term Context:")
        system_prompt_parts.append("- " + "\n- ".join(long_term))
        system_prompt_parts.append("\nUse this context to better understand the user's preferences and past interactions.")
    
    # Add the core principles and rules
    system_prompt_parts.append("""
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
- ONLY use the provided MCP browser tools. DO NOT try to write or execute raw JavaScript code.
- Use browser_snapshot to read page content instead of trying to evaluate JavaScript.
- Use browser_click and browser_type for interactions - these tools handle everything automatically.
- IMPORTANT: You are working on a specific browser tab that has been selected for you. All actions (snapshot, click, type, navigate) will happen on the currently selected tab.

Remember: Think step-by-step, verify each action, and always use fresh snapshots before interacting.""")
    
    # Combine all system prompt parts
    system_prompt = "\n".join(system_prompt_parts)
    
    # Create agent with enhanced system prompt including user info and long-term memory
    agent = create_agent(
        model=tools_llm,
        tools=_mcp_tools,
        system_prompt=system_prompt
    )

    # Execute and stream logs to server stdout (optional)
    try:
        print(f"\n[DEBUG] Starting agent execution for: {user_text}\n")
        print(f"[DEBUG] Execution plan:\n{execution_plan}\n")
        messages_so_far = [HumanMessage(content=instruction)]
        result = None
        streamed_messages: list[AnyMessage] = []

        async for chunk in agent.astream({"messages": messages_so_far}):
            # The stream yields step-wise partial outputs. We must accumulate messages across chunks.
            for key, value in chunk.items():
                if isinstance(value, dict) and "messages" in value and isinstance(value["messages"], list):
                    for msg in value["messages"]:
                        # Accumulate for final extraction
                        if isinstance(msg, (HumanMessage, AIMessage, SystemMessage)) or hasattr(msg, "type"):
                            streamed_messages.append(msg)

                        msg_type = type(msg).__name__
                        print(f"[DEBUG] Step - {msg_type}:")
                        if hasattr(msg, "content") and msg.content:
                            content_str = str(msg.content)
                            print("  Content:", (content_str[:300] + "...") if len(content_str) > 300 else content_str)
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            print(f"  Tool calls: {[tc.get('name', 'unknown') for tc in msg.tool_calls]}")
                            for tc in msg.tool_calls:
                                if "args" in tc:
                                    print(f"    Args: {tc['args']}")
                        if hasattr(msg, "tool_call_id"):
                            print(f"  Tool result (ID: {msg.tool_call_id})")
            result = chunk

        # Prefer accumulated stream messages (most reliable); fall back to the last chunk shape if needed.
        final_messages = streamed_messages
        if not final_messages and isinstance(result, dict):
            final_messages = result.get("messages", []) or []

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
            error_summary = "\n\n⚠️ Action did not complete successfully. " + (
                error_details[0] if error_details else "Please check the browser window for details."
            )
            response_text = final_text + error_summary
        else:
            # Add explicit success confirmation (users look for this in the chat UI)
            success_confirmation = "\n\n✅ Action completed successfully."
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
        elif "not well-serializable" in error_msg.lower() or "evaluatefunction" in error_msg.lower():
            friendly_error = "⛔ Browser automation error: Invalid JavaScript code format. The task encountered a technical issue with executing code on the page. Please try rephrasing your request or try again."
            print(f"[ERROR] Playwright serialization error - this may indicate the MCP tools received malformed code")
        elif "page.evaluate" in error_msg.lower():
            friendly_error = "⛔ Browser automation error: Failed to execute JavaScript on the page. Please try a different approach or rephrase your request."
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

async def reply_wrapped(state: ChatState, config) -> ChatState:
    page_content = config["configurable"].get("page_content", None)
    return await reply_node(state, page_content=page_content)

# Add all nodes
builder.add_node("reply", reply_wrapped)
builder.add_node("trim", trim_node)

async def mcp_wrapped(state: ChatState, config) -> ChatState:
    """Wrapper to pass config to mcp_node"""
    return await mcp_node(state, config=config)

builder.add_node("mcp", mcp_wrapped)  # MCP node for browser automation
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

# Initialize graph (will be set up in lifespan)
graph = None

# ===== API =====
class PageContentData(BaseModel):
    url: str
    title: str
    text: str
    headings: List[str]

class ChatIn(BaseModel):
    message: str
    agentic_mode: bool = False  # Whether to use agentic mode (MCP tools)
    page_content: PageContentData | None = None  # Page content for context in non-agentic mode
    tab_index: int | None = None  # Chrome tab index (0-based) to select in Playwright browser

class OpenIn(BaseModel):
    url: str | None = "https://github.com"

class UserInfoUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None  # ISO format: YYYY-MM-DD
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    additional_info: Optional[str] = None  # Additional information about the user

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage MCP client lifecycle and user database for the whole app lifetime."""
    global graph, _mcp_client, _mcp_session, _mcp_tools
    
    # Initialize user database
    await init_user_db()
    
    # Create MCP client
    # Use absolute path for MCP data directory
    mcp_data_path = os.path.abspath(MCP_DATA_DIR)
    init_script_path = os.path.abspath(INIT_SCRIPT_PATH)
    servers = {
        "playwright": {
            "transport": "stdio",
            "command": NPM,
            "args": ["-y", "@playwright/mcp@0.0.56", f"--user-data-dir={mcp_data_path}", f"--init-script={init_script_path}"],
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

        # Compile graph without checkpointer (no state persistence)
        graph = builder.compile()
        
        yield  # App runs here - browser stays open
    
    # Cleanup: Session closes here, browser will close
    await close_user_db()

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

@app.get("/user/info")
async def get_user_info_endpoint():
    """Get user information from database (source of truth)."""
    try:
        user_info = await get_user_info()
        return {"ok": True, "user_info": user_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user info: {str(e)}")

@app.post("/user/info")
async def update_user_info_endpoint(info: UserInfoUpdate):
    """Update user information in database."""
    try:
        # Convert Pydantic model to dict, excluding None values
        info_dict = {k: v for k, v in info.model_dump().items() if v is not None}
        if info_dict:
            await update_user_info(info_dict)
            return {"ok": True, "message": "User information updated successfully"}
        else:
            return {"ok": True, "message": "No fields to update"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update user info: {str(e)}")
    
@app.get("/status")
async def status():
    return {
        "playwright_active": _mcp_session is not None and _mcp_tools is not None,
    }

@app.post("/chat")
async def chat(inp: ChatIn):
    try:
        # Ensure MCP is alive
        try:
            await get_mcp_client_and_tools()
        except RuntimeError as e:
            error_msg = f"MCP client not initialized: {str(e)}"
            print(f"[ERROR] {error_msg}")
            raise HTTPException(status_code=503, detail=error_msg)
        except Exception as e:
            error_msg = f"Failed to get MCP client: {str(e)}"
            print(f"[ERROR] {error_msg}")
            raise HTTPException(status_code=503, detail=error_msg)

        # Check if graph is initialized
        if graph is None:
            error_msg = "Graph not initialized. Server may still be starting up."
            print(f"[ERROR] {error_msg}")
            raise HTTPException(status_code=503, detail=error_msg)

        # Log the agentic_mode setting for debugging
        print(f"[DEBUG] Chat request - agentic_mode: {inp.agentic_mode}, message: {inp.message[:50]}...")
        if inp.page_content:
            print(f"[DEBUG] Page content provided - URL: {inp.page_content.url}, Title: {inp.page_content.title}")

        # Prepare config with page content for non-agentic mode
        config_data = {
            "agentic_mode": inp.agentic_mode
        }
        
        # Add tab_index if provided (for selecting correct tab in Playwright browser)
        if inp.tab_index is not None:
            config_data["tab_index"] = inp.tab_index
            print(f"[DEBUG] Tab index provided: {inp.tab_index}")
        
        # Add page content to config if provided (for non-agentic mode)
        if inp.page_content:
            config_data["page_content"] = {
                "url": inp.page_content.url,
                "title": inp.page_content.title,
                "text": inp.page_content.text,
                "headings": inp.page_content.headings
            }

        # Use ainvoke for async graph execution (required for async nodes like mcp_node)
        try:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=inp.message)]},
                config={"configurable": config_data},
            )
        except Exception as e:
            error_msg = f"Graph execution failed: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(f"[ERROR] Exception type: {type(e).__name__}")
            import traceback
            print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to process message: {str(e)}")

        # Extract reply from result
        try:
            ai_messages = [m for m in result.get("messages", []) if isinstance(m, AIMessage)]
            if not ai_messages:
                error_msg = "No AI response generated. Result messages: " + str([type(m).__name__ for m in result.get("messages", [])])
                print(f"[ERROR] {error_msg}")
                raise HTTPException(status_code=500, detail="No response generated from AI")
            reply = ai_messages[-1].content
        except (KeyError, IndexError, AttributeError) as e:
            error_msg = f"Failed to extract reply from result: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(f"[ERROR] Result keys: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
            print(f"[ERROR] Result: {result}")
            raise HTTPException(status_code=500, detail=error_msg)

        # Try to add memories (non-critical, don't fail if this errors)
        try:
            add_memories(
                docs=[f"User said: {inp.message}", f"Assistant replied: {reply}"],
                metadata={"kind": "chat"},
            )
        except Exception as e:
            print(f"[WARNING] Failed to save memories (non-critical): {str(e)}")

        return {"reply": reply}
        
    except HTTPException:
        # Re-raise HTTP exceptions (these are expected errors)
        raise
    except Exception as e:
        # Catch any other unexpected errors
        error_msg = f"Unexpected error in chat endpoint: {str(e)}"
        error_type = type(e).__name__
        print(f"[ERROR] {error_msg}")
        print(f"[ERROR] Exception type: {error_type}")
        import traceback
        print(f"[ERROR] Full traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {error_msg} (type: {error_type})")

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

def run():
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    run()