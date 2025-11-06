# pip install fastapi uvicorn langgraph langchain langchain-openai langchain-community chromadb tiktoken langchain-mcp-adapters

import os
from dotenv import load_dotenv

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
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import add_messages

# ===== Config =====
WINDOW = 8
TOP_K = 4
SQLITE_URL = "sqlite:///memory.sqlite"
CHROMA_DIR = "chroma"

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

async def mcp_node(state: ChatState) -> ChatState:
    """
    Optional: START -> mcp_node -> reply_node -> trim_node -> END
    Uses the Playwright MCP server (stdio) and an OpenAI tools agent.
    """
    last_user = next((m for m in reversed(state["messages"]) if m.type == "human"), None)
    user_text = (last_user.content if last_user else "").strip()
    if not user_text:
        return {"messages": [AIMessage(content="(no user message to act on)")]}
    
    servers = {
        "playwright": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@microsoft/playwright-mcp"],  
        }
    }
    client_kwargs = {
        "throw_on_load_error": True,
        "prefix_tool_name_with_server_name": True,
        "additional_tool_name_prefix": "mcp",
    }

    tools_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    async with MultiServerMCPClient(servers, **client_kwargs) as client:
        tools = await client.get_tools()  # MCP → LangChain Tool objects

        # Use langchain 1.0+ create_agent API
        agent = create_agent(
            model=tools_llm,
            tools=tools,
            system_prompt="You may call tools to complete the user's request. Prefer minimal steps; stop when done."
        )
        
        # Invoke the agent directly (it's already a compiled graph)
        result = await agent.ainvoke({"messages": [HumanMessage(content=user_text)]})

    # Extract the final AI message
    final_messages = result.get("messages", [])
    final_ai_message = next((m for m in reversed(final_messages) if isinstance(m, AIMessage)), None)
    final_text = final_ai_message.content if final_ai_message else str(result)
    
    return {"messages": [AIMessage(content=final_text)]}

def trim_node(state: ChatState) -> ChatState:
    return {"messages": state["messages"][-WINDOW:]}

# ===== Graph =====
builder = StateGraph(ChatState)

def reply_wrapped(state: ChatState, config) -> ChatState:
    uid = config["configurable"].get("user_id", "anon")
    return reply_node(state, user_id=uid)

# Baseline path: reply -> trim (add a router + mcp if you want the MCP-first flow)
builder.add_node("reply", reply_wrapped)
builder.add_node("trim", trim_node)
# builder.add_node("mcp", mcp_node)  # <- if you want to route START to MCP first
builder.set_entry_point("reply")
builder.add_edge("reply", "trim")
builder.add_edge("trim", END)

checkpointer = SqliteSaver.from_conn_string(SQLITE_URL)
graph = builder.compile(checkpointer=checkpointer)

# ===== API =====
class ChatIn(BaseModel):
    user_id: str
    thread_id: str
    message: str

app = FastAPI()

@app.post("/chat")
def chat(inp: ChatIn):
    result = graph.invoke(
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

# Run: uvicorn app:app --reload
