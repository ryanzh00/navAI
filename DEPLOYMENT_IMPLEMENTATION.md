# Multi-Client Deployment Implementation

This document provides specific code changes to support multiple clients in production.

## Overview of Changes

1. Replace SQLite with PostgreSQL for checkpoints
2. Implement per-user browser sessions
3. Add authentication middleware
4. Add configuration management
5. Add resource cleanup and limits

---

## Step 1: Update Dependencies

Add to `requirements.txt`:

```txt
# Database
psycopg2-binary==2.9.9
asyncpg==0.29.0
langgraph-checkpoint-postgres==3.0.0

# Authentication
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# Configuration
pydantic-settings==2.11.0

# Production server
gunicorn==21.2.0
```

---

## Step 2: Create Configuration Module

Create `backend/langgraph/config.py`:

```python
import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: Optional[str] = None  # PostgreSQL connection string
    SQLITE_URL: Optional[str] = None  # Fallback to SQLite for dev
    
    # Browser Configuration
    BROWSER_POOL_SIZE: int = 10
    BROWSER_TIMEOUT: int = 300  # seconds before closing idle browser
    MAX_BROWSERS_PER_USER: int = 1
    
    # Authentication
    AUTH_REQUIRED: bool = False
    JWT_SECRET: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    
    # Deployment
    DEPLOYMENT_MODE: str = "single"  # single, pool, serverless
    NPM_BIN: str = os.getenv("NPM_BIN", "/opt/homebrew/bin/npx")
    
    # ChromaDB
    CHROMA_DIR: Optional[str] = None
    
    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
```

---

## Step 3: Per-User Browser Session Manager

Create `backend/langgraph/browser_manager.py`:

```python
import asyncio
import time
from typing import Dict, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from config import settings

class BrowserSession:
    def __init__(self, user_id: str, client: MultiServerMCPClient, session, tools):
        self.user_id = user_id
        self.client = client
        self.session = session
        self.tools = tools
        self.last_used = time.time()
        self.use_count = 0
    
    def update_activity(self):
        self.last_used = time.time()
        self.use_count += 1
    
    def is_idle(self, timeout: int) -> bool:
        return time.time() - self.last_used > timeout

class BrowserManager:
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def get_browser_session(self, user_id: str) -> BrowserSession:
        """Get or create browser session for user."""
        async with self._lock:
            # Check if session exists and is still active
            if user_id in self.sessions:
                session = self.sessions[user_id]
                session.update_activity()
                return session
            
            # Create new session
            servers = {
                "playwright": {
                    "transport": "stdio",
                    "command": settings.NPM_BIN,
                    "args": ["-y", "@playwright/mcp@latest", f"--user-data-dir=./mcp_data/{user_id}"],
                }
            }
            
            client = MultiServerMCPClient(connections=servers)
            session_context = client.session("playwright")
            session = await session_context.__aenter__()
            tools = await load_mcp_tools(session)
            
            browser_session = BrowserSession(user_id, client, session, tools)
            self.sessions[user_id] = browser_session
            
            # Start cleanup task if not running
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_idle_sessions())
            
            return browser_session
    
    async def close_session(self, user_id: str):
        """Close browser session for user."""
        async with self._lock:
            if user_id in self.sessions:
                session = self.sessions[user_id]
                try:
                    await session.session.__aexit__(None, None, None)
                except:
                    pass
                del self.sessions[user_id]
    
    async def _cleanup_idle_sessions(self):
        """Periodically close idle browser sessions."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                async with self._lock:
                    idle_users = [
                        uid for uid, sess in self.sessions.items()
                        if sess.is_idle(settings.BROWSER_TIMEOUT)
                    ]
                    for user_id in idle_users:
                        await self.close_session(user_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in cleanup task: {e}")
    
    async def close_all(self):
        """Close all browser sessions (for shutdown)."""
        async with self._lock:
            for user_id in list(self.sessions.keys()):
                await self.close_session(user_id)

# Global browser manager instance
browser_manager = BrowserManager()
```

---

## Step 4: Database Configuration with PostgreSQL Support

Update the database initialization in `main.py`:

```python
from config import settings

# Determine which checkpointer to use
if settings.DATABASE_URL:
    # PostgreSQL (production)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
elif settings.SQLITE_URL:
    # SQLite (development)
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpointer = AsyncSqliteSaver.from_conn_string(settings.SQLITE_URL)
else:
    # Default SQLite path
    SQLITE_URL = os.path.join(BASE_DIR, "memory.sqlite")
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpointer = AsyncSqliteSaver.from_conn_string(f"sqlite+aiosqlite:///{SQLITE_URL}")
```

---

## Step 5: Authentication Middleware

Create `backend/langgraph/auth.py`:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from config import settings
from typing import Optional

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify JWT token and return user_id."""
    if not settings.AUTH_REQUIRED:
        # In development, extract user_id from token if present
        # Otherwise allow anonymous access
        return "anon"
    
    token = credentials.credentials
    
    if not settings.JWT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET not configured"
        )
    
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str = payload.get("sub") or payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token: missing user_id"
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )

def verify_user_match(user_id_from_token: str, user_id_from_request: str):
    """Verify that authenticated user matches request user_id."""
    if settings.AUTH_REQUIRED and user_id_from_token != user_id_from_request:
        raise HTTPException(
            status_code=403,
            detail="User ID mismatch"
        )
```

---

## Step 6: Update Main Application

Key changes to `main.py`:

1. **Remove global MCP client**, use BrowserManager instead
2. **Update lifespan** to initialize database based on config
3. **Update chat endpoint** to use per-user browsers
4. **Add authentication** to endpoints

Example changes:

```python
from browser_manager import browser_manager
from auth import verify_token, verify_user_match
from config import settings

# Remove global _mcp_client, _mcp_session, _mcp_tools

async def mcp_node(state: ChatState, *, user_id: str) -> ChatState:
    """MCP node using per-user browser session."""
    session = await browser_manager.get_browser_session(user_id)
    tools = session.tools
    
    # Rest of the function uses session.tools instead of _mcp_tools
    # ...

@app.post("/chat")
async def chat(
    inp: ChatIn,
    authenticated_user_id: str = Depends(verify_token)
):
    verify_user_match(authenticated_user_id, inp.user_id)
    
    # Rest of the function...
```

---

## Step 7: Environment Configuration

Create `.env.example`:

```env
# Database
# For production: Use PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/navai

# For development: Use SQLite (leave DATABASE_URL empty)
SQLITE_URL=sqlite+aiosqlite:///./memory.sqlite

# Browser Settings
BROWSER_POOL_SIZE=10
BROWSER_TIMEOUT=300
MAX_BROWSERS_PER_USER=1

# Authentication
AUTH_REQUIRED=false
JWT_SECRET=your-secret-key-here-change-in-production
JWT_ALGORITHM=HS256

# Deployment
DEPLOYMENT_MODE=single
NPM_BIN=/opt/homebrew/bin/npx

# ChromaDB
CHROMA_DIR=./chroma

# OpenAI
OPENAI_API_KEY=your-openai-api-key
```

---

## Step 8: Production Deployment Script

Create `backend/langgraph/deploy.sh`:

```bash
#!/bin/bash
set -e

echo "Starting deployment..."

# Check if PostgreSQL is configured
if [ -z "$DATABASE_URL" ]; then
    echo "Warning: DATABASE_URL not set. Using SQLite (not recommended for production)"
fi

# Run database migrations (if needed)
# LangGraph creates tables automatically on first connection

# Start application with gunicorn
exec gunicorn main:app \
    --workers ${WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind ${HOST:-0.0.0.0}:${PORT:-8000} \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

---

## Migration Checklist

- [ ] Install PostgreSQL dependencies
- [ ] Set up PostgreSQL database
- [ ] Create configuration module (`config.py`)
- [ ] Create browser manager (`browser_manager.py`)
- [ ] Create auth module (`auth.py`)
- [ ] Update `main.py` to use new modules
- [ ] Set environment variables
- [ ] Test with multiple concurrent users
- [ ] Set up monitoring/logging
- [ ] Configure reverse proxy (nginx)
- [ ] Enable HTTPS
- [ ] Set up backups for database

---

## Testing Multi-Client Setup

1. **Test concurrent users**:
   ```python
   import asyncio
   import httpx
   
   async def test_concurrent():
       async with httpx.AsyncClient() as client:
           tasks = []
           for i in range(5):
               tasks.append(client.post(
                   "http://localhost:8000/chat",
                   json={"user_id": f"user_{i}", "thread_id": f"thread_{i}", "message": "Hello"}
               ))
           results = await asyncio.gather(*tasks)
           print(results)
   ```

2. **Verify browser isolation**: Each user should have separate browser state

3. **Check database**: Verify checkpoints are stored per user/thread

4. **Test authentication**: Verify unauthorized requests are rejected

---

## Rollback Plan

If issues arise:

1. **Revert to SQLite**: Set `DATABASE_URL=""` and `SQLITE_URL=...`
2. **Disable auth**: Set `AUTH_REQUIRED=false`
3. **Single browser**: Temporarily revert to global browser (for debugging)

---

## Next Steps

1. Review this implementation guide
2. Start with Step 1 (dependencies)
3. Test each step incrementally
4. Deploy to staging environment first
5. Monitor and iterate


