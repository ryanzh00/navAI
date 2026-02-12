# navAI

A browser automation assistant using LangGraph and Playwright MCP.

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Multi-client deployment guide and architecture options
- **[DEPLOYMENT_IMPLEMENTATION.md](DEPLOYMENT_IMPLEMENTATION.md)** - Step-by-step implementation guide for production deployment
- **[PLAYWRIGHT_MCP_SETUP.md](PLAYWRIGHT_MCP_SETUP.md)** - Setup guide for Playwright MCP Chrome Extension

## Quick Start

### Local Development

1. Install dependencies:
   ```bash
   cd backend/langgraph
   pip install -r requirements.txt
   ```

2. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your OPENAI_API_KEY
   ```

3. Run the server:
   ```bash
   uvicorn main:app --reload
   ```

### Production Deployment

For deploying with multiple clients, see:
- [DEPLOYMENT.md](DEPLOYMENT.md) - Overview and architecture options
- [DEPLOYMENT_IMPLEMENTATION.md](DEPLOYMENT_IMPLEMENTATION.md) - Implementation details

Key considerations for multi-client deployment:
- Per-user browser sessions (currently uses shared browser)
- PostgreSQL database (currently uses SQLite)
- Authentication middleware
- Resource management and cleanup