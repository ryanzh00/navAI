# Deployment Architecture Analysis

## Current Architecture

Your current implementation has:

```
┌─────────────────┐
│  FastAPI Server │
│   (Single App)  │
└────────┬────────┘
         │
    ┌────▼─────────────────────┐
    │  Single MCP Client       │
    │  (Global, Shared)        │
    │                          │
    │  ┌──────────────────┐   │
    │  │ Playwright       │   │
    │  │ Browser Instance │   │
    │  │ (One Browser)    │   │
    │  └──────────────────┘   │
    └──────────────────────────┘
         │
    ┌────▼────┐  ┌─────┐  ┌─────┐
    │ User 1  │  │User2│  │User3│
    │ Requests│  │     │  │     │
    └─────────┘  └─────┘  └─────┘
```

**Problem**: All users share the same browser instance and tabs. User 1's actions affect User 2!

---

## Deployment Scenarios

### Scenario 1: Current Setup (Local/Single User)
- ✅ Works fine for development
- ✅ One browser, one user
- ❌ Multiple users will interfere with each other

### Scenario 2: Small Scale Production (10-50 users)

**Option A: Per-User Browser Instances**

```
┌─────────────────┐
│  FastAPI Server │
└────────┬────────┘
         │
    ┌────▼────────────────────────────┐
    │  Browser Manager                │
    │  ┌──────────┐  ┌──────────┐   │
    │  │ User 1   │  │ User 2   │   │
    │  │ Browser  │  │ Browser  │   │
    │  └──────────┘  └──────────┘   │
    │  ┌──────────┐  ┌──────────┐   │
    │  │ User 3   │  │ User 4   │   │
    │  │ Browser  │  │ Browser  │   │
    │  └──────────┘  └──────────┘   │
    └────────────────────────────────┘
```

**Implementation**: 
- Create MCP client per `user_id` on first request
- Store in a dictionary: `{user_id: MCPClient}`
- Clean up inactive sessions after timeout
- Memory usage: ~500MB per browser instance

**Limitations**:
- Can't scale beyond ~50-100 users on a single server
- Each browser uses significant RAM

### Scenario 3: Medium Scale (50-200 users)

**Option B: Browser Pool with Round-Robin**

```
┌─────────────────┐
│  Load Balancer  │
└────────┬────────┘
         │
    ┌────▼────────┐  ┌──────────────┐
    │  Server 1   │  │  Server 2    │
    └────┬────────┘  └──────┬───────┘
         │                   │
    ┌────▼────────┐     ┌────▼────────┐
    │ Browser     │     │ Browser     │
    │ Pool (10)   │     │ Pool (10)   │
    └─────────────┘     └─────────────┘
```

**Implementation**:
- Pre-create N browser instances per server
- Assign browsers to users round-robin or on-demand
- Return browser to pool after use
- Session affinity (sticky sessions) via load balancer

**Trade-offs**:
- Users might switch browsers between requests
- More efficient resource usage
- Can handle more concurrent users

### Scenario 4: Large Scale (200+ users)

**Option C: Dedicated Browser Services**

```
┌─────────────────┐
│  FastAPI Servers│  (Stateless API)
└────────┬────────┘
         │
    ┌────▼─────────────────────────┐
    │  Browser Service             │
    │  (Separate microservice)     │
    │                              │
    │  ┌────────────────────────┐ │
    │  │ Browser Orchestrator   │ │
    │  │ - Assigns browsers     │ │
    │  │ - Manages lifecycle    │ │
    │  └────────────────────────┘ │
    │                              │
    │  ┌──────┐ ┌──────┐ ┌──────┐ │
    │  │Browser│ │Browser│ │Browser│ │
    │  │Pool 1 │ │Pool 2 │ │Pool 3 │ │
    │  └──────┘ └──────┘ └──────┘ │
    └──────────────────────────────┘
```

**Implementation**:
- Separate service for browser management
- FastAPI servers are stateless
- Browser service handles all MCP operations
- Can scale browsers independently from API servers

---

## Recommended Approach for Your Use Case

Given that you're using **Playwright MCP with a headed browser**, I recommend:

### **Option: Per-User Browser Sessions** (Scenario 2, Option A)

**Why?**
- You already have tab selection working (via `tab_index`)
- Headed browsers are easier to debug
- Simpler architecture for your scale
- Better user isolation

**Implementation Changes Needed**:

1. **Create Browser Manager**:

```python
# browser_manager.py
from typing import Dict, Optional
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

class BrowserManager:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}  # {user_id: {client, session, tools}}
        self._lock = asyncio.Lock()
    
    async def get_browser_session(self, user_id: str):
        async with self._lock:
            if user_id in self.sessions:
                return self.sessions[user_id]
            
            # Create new MCP client for this user
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": NPM,
                    "args": ["-y", "@playwright/mcp@latest", f"--user-data-dir=./mcp_data/{user_id}"],
                }
            }
            client = MultiServerMCPClient(connections=servers)
            session_context = client.session("playwright")
            session = await session_context.__aenter__()
            tools = await load_mcp_tools(session)
            
            self.sessions[user_id] = {
                "client": client,
                "session": session,
                "tools": tools
            }
            return self.sessions[user_id]
```

2. **Update `mcp_node` to use per-user browser**:

```python
# In main.py
browser_manager = BrowserManager()

async def mcp_node(state: ChatState, config=None) -> ChatState:
    # Get user_id from config
    user_id = config.get("configurable", {}).get("user_id", "default")
    
    # Get or create browser session for this user
    browser_session = await browser_manager.get_browser_session(user_id)
    user_tools = browser_session["tools"]
    
    # Use user_tools instead of global _mcp_tools
    # ... rest of the function
```

3. **Add Session Cleanup**:
- Close inactive sessions after 30 minutes
- Limit max concurrent sessions per server
- Clean up on server shutdown

---

## Deployment Platforms

### Railway / Render / Fly.io (Easiest)

```yaml
# Dockerfile
FROM python:3.11
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    nodejs npm

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Pros**: Simple, auto-scaling, managed databases
**Cons**: Browser automation in containers requires Xvfb or headless mode

### AWS / GCP / Azure (More Control)

- Use EC2/Compute Engine with GUI support
- Or use ECS/Fargate with headless browsers
- Managed PostgreSQL for state
- Load balancer for multiple instances

### Kubernetes (Production Scale)

- Each pod can handle N concurrent browsers
- Auto-scale based on CPU/memory
- Separate browser pods from API pods
- Use StatefulSets for browser persistence

---

## Resource Planning

**Per Browser Instance**:
- RAM: ~300-500 MB
- CPU: Low when idle, spikes during actions
- Disk: ~100 MB (user data, cache)

**Server Requirements** (50 concurrent users):
- CPU: 8-16 cores
- RAM: 32-64 GB (50 browsers × 500MB = 25GB + overhead)
- Storage: 10-50 GB SSD

---

## Key Deployment Considerations

1. **State Management**:
   - Use PostgreSQL instead of SQLite
   - Shared ChromaDB or cloud vector DB
   - Redis for session management

2. **Browser Lifecycle**:
   - Clean up after inactivity
   - Handle browser crashes gracefully
   - Restart browsers on errors

3. **Security**:
   - Authentication middleware
   - Rate limiting
   - User isolation (already handled by per-user browsers)

4. **Monitoring**:
   - Track browser count per server
   - Monitor memory usage
   - Alert on browser failures

5. **Scaling Strategy**:
   - Start with single server, per-user browsers
   - Add more servers when hitting limits
   - Consider headless browsers for scale

---

## Quick Start: Single Server Deployment

1. **Update to per-user browsers** (see implementation above)
2. **Use PostgreSQL**:
   ```python
   from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
   checkpointer = AsyncPostgresSaver.from_conn_string("postgresql://...")
   ```
3. **Deploy to Railway/Render**:
   - Connect GitHub repo
   - Set environment variables
   - Deploy!

4. **Monitor and scale** as needed

---

Would you like me to implement the per-user browser manager for your codebase?

