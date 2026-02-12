# Multi-Client Deployment Guide

## Current Architecture Issues

Your current backend is designed for single-user local development. For production deployment with multiple clients, you'll need to address several architectural challenges:

### 1. **Shared Browser Instance**

- **Problem**: All users share a single MCP browser instance (`_mcp_client`)
- **Impact**: Browser state conflicts, users interfering with each other's sessions
- **Solution**: Per-user browser sessions or browser pool

### 2. **SQLite Database Limitations**

- **Problem**: SQLite doesn't handle concurrent writes well across multiple processes
- **Impact**: Database locks, poor performance, potential data corruption
- **Solution**: Migrate to PostgreSQL or use database-per-user pattern

### 3. **Local File Storage**

- **Problem**: ChromaDB and SQLite files are local to the server
- **Impact**: Can't scale horizontally, single point of failure
- **Solution**: Use cloud storage or distributed databases

### 4. **No Authentication/Authorization**

- **Problem**: Any client can access any user_id's data
- **Impact**: Security risk, data leaks
- **Solution**: Add authentication middleware

---

## Deployment Options

### Option 1: Single Server with Per-User Browsers (Recommended for Small Scale)

**Best for**: 10-50 concurrent users

**Architecture**:

- One FastAPI server instance
- Per-user browser sessions (create browser on first request per user)
- PostgreSQL for checkpoints
- Shared ChromaDB with user namespacing (already implemented)
- Authentication middleware

**Pros**:

- Simple deployment
- Good isolation between users
- No complex infrastructure

**Cons**:

- Limited by server resources (memory/CPU)
- Browser instances consume significant resources

**Implementation**:

- Browser pool or lazy initialization per user_id
- Session cleanup after inactivity

---

### Option 2: Load Balanced with Browser Pool

**Best for**: 50-200 concurrent users

**Architecture**:

- Multiple FastAPI server instances (load balanced)
- Shared browser pool (or per-server pools)
- PostgreSQL for shared state
- Redis for session management
- Distributed ChromaDB or cloud vector store

**Pros**:

- Horizontal scaling
- Better resource utilization
- Higher availability

**Cons**:

- More complex infrastructure
- Requires load balancer configuration
- Browser pool management complexity

---

### Option 3: Serverless/Container-Based

**Best for**: Variable load, auto-scaling needs

**Architecture**:

- Containerized FastAPI (Docker)
- Kubernetes or container orchestration
- Each container handles requests for specific users
- Cloud database (PostgreSQL, etc.)
- Cloud vector store (Pinecone, Weaviate, etc.)

**Pros**:

- Auto-scaling
- Pay for what you use
- High availability

**Cons**:

- Most complex setup
- Browser automation in containers requires special configuration
- Cold start times

---

## Implementation Steps

### Step 1: Database Migration

Replace SQLite with PostgreSQL:

```python
# Instead of AsyncSqliteSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import asyncpg

# Connection string format:
# postgresql://user:password@host:port/database
```

**Database Setup**:

```sql
-- Create database
CREATE DATABASE navai;

-- LangGraph will create tables automatically when checkpointer initializes
```

### Step 2: Per-User Browser Sessions

Currently, browsers are global. Change to per-user:

**Option A: Lazy initialization per user**

- Create browser session on first request per user_id
- Store in dict: `{user_id: browser_session}`
- Cleanup after timeout

**Option B: Browser pool**

- Pre-create N browser instances
- Assign to users round-robin or on-demand
- Return to pool after use

### Step 3: Add Authentication

Add middleware to validate user sessions:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    # Validate JWT or API key
    token = credentials.credentials
    user_id = validate_token(token)  # Your validation logic
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id

@app.post("/chat")
async def chat(inp: ChatIn, user_id: str = Depends(verify_token)):
    # Ensure user_id matches authenticated user
    if inp.user_id != user_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")
    # ... rest of code
```

### Step 4: Environment Configuration

Create environment-based config:

```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///memory.sqlite"  # Default for dev
    POSTGRES_URL: str | None = None  # Use if set

    # Browser
    BROWSER_POOL_SIZE: int = 10
    BROWSER_TIMEOUT: int = 300  # seconds

    # Auth
    AUTH_REQUIRED: bool = False  # Enable in production
    JWT_SECRET: str | None = None

    # Deployment
    DEPLOYMENT_MODE: str = "single"  # single, pool, serverless

    class Config:
        env_file = ".env"

settings = Settings()
```

### Step 5: Resource Management

Add cleanup and limits:

- **Memory limits**: Set max browsers per server
- **Timeout handling**: Close inactive browser sessions
- **Rate limiting**: Prevent abuse
- **Monitoring**: Track resource usage

---

## Recommended Deployment Architecture (Option 1)

For your first production deployment, I recommend **Option 1** with these components:

```
┌─────────────────┐
│   Load Balancer │  (nginx or cloud LB)
└────────┬────────┘
         │
    ┌────▼────┐
    │ FastAPI │  (single instance or 2-3 for redundancy)
    │ Server  │
    └────┬────┘
         │
    ┌────▼──────────────────────┐
    │                           │
┌───▼──┐  ┌──────────┐  ┌──────▼──┐
│Post- │  │ ChromaDB │  │ Browser │
│gres  │  │(per user │  │  Pool   │
│      │  │  namesp.)│  │         │
└──────┘  └──────────┘  └─────────┘
```

### Infrastructure Requirements:

1. **Server**:

   - 4-8 CPU cores
   - 16-32 GB RAM
   - SSD storage
   - Can handle 10-50 concurrent browsers

2. **PostgreSQL**:

   - Managed service (AWS RDS, Google Cloud SQL, etc.)
   - Or self-hosted with backups

3. **Deployment Platform**:
   - VPS (DigitalOcean, Linode, etc.)
   - Cloud VM (AWS EC2, GCP Compute, Azure VM)
   - Container platform (Railway, Render, Fly.io)

---

## Quick Start: Single Server Deployment

### 1. Set up PostgreSQL

```bash
# Install PostgreSQL (Ubuntu/Debian)
sudo apt-get install postgresql postgresql-contrib

# Create database
sudo -u postgres createdb navai
sudo -u postgres psql -c "CREATE USER navai_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE navai TO navai_user;"
```

### 2. Update Environment Variables

Create `.env.production`:

```env
# Database
POSTGRES_URL=postgresql://navai_user:your_password@localhost:5432/navai

# Deployment
DEPLOYMENT_MODE=single
BROWSER_POOL_SIZE=10
AUTH_REQUIRED=true

# Security
JWT_SECRET=your-jwt-secret-key-here
OPENAI_API_KEY=your-openai-key

# Server
HOST=0.0.0.0
PORT=8000
```

### 3. Install Dependencies

```bash
pip install psycopg2-binary asyncpg langgraph-checkpoint-postgres
```

### 4. Deploy with Process Manager

```bash
# Install gunicorn for production
pip install gunicorn

# Run with gunicorn + uvicorn workers
gunicorn main:app \
  --workers 2 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

### 5. Add Reverse Proxy (nginx)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Monitoring & Maintenance

### Metrics to Track:

1. **Browser instances**: Number of active browsers
2. **Memory usage**: Per browser (~200-500MB each)
3. **Response times**: Chat endpoint latency
4. **Database connections**: PostgreSQL connection pool
5. **Error rates**: Failed requests

### Logging:

- Use structured logging (JSON format)
- Log user_id, thread_id, errors
- Monitor browser crashes/restarts

### Cleanup:

- Close inactive browser sessions (>5 min idle)
- Archive old chat threads
- Clean up old vector store entries

---

## Security Considerations

1. **Authentication**: Require API keys or JWT tokens
2. **Rate Limiting**: Prevent abuse (e.g., 100 requests/user/hour)
3. **Input Validation**: Sanitize all user inputs
4. **HTTPS**: Use SSL/TLS in production
5. **User Isolation**: Verify user_id matches authenticated user
6. **Secrets Management**: Use environment variables or secret managers

---

## Cost Estimation (Example)

**Small Scale (Option 1)**:

- VPS (4 CPU, 16GB RAM): $40-80/month
- PostgreSQL (managed): $15-30/month
- Total: ~$55-110/month

**Medium Scale (Option 2)**:

- 2-3 VPS instances: $120-240/month
- PostgreSQL + Redis: $50-100/month
- Load balancer: $20/month
- Total: ~$190-360/month

---

## Next Steps

See `DEPLOYMENT_IMPLEMENTATION.md` for code changes needed to implement Option 1.

