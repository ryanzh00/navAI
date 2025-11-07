# Playwright MCP Chrome Extension Setup Guide

This guide explains how to set up Playwright MCP with Chrome Extension support to control the user's actual Chrome browser (preserving sessions and cookies).

## Overview

There are two modes for Playwright MCP:

1. **Stdio Mode (Default)**: Launches a separate browser instance - no user session
2. **Chrome Extension Mode**: Connects to user's Chrome browser - preserves session/cookies

## Prerequisites

- Node.js and npm installed
- Chrome browser
- Playwright MCP Chrome Extension installed

## Step 1: Install Playwright MCP Chrome Extension

### Option A: From Chrome Web Store
1. Visit the [Chrome Web Store](https://chromewebstore.google.com/detail/browser-mcp-automate-your/bjfgambnhccakkhmkepdoekmckoijdlc)
2. Click "Add to Chrome"
3. The extension will be installed automatically

### Option B: From GitHub (Development)
1. Clone or download the [Playwright MCP Extension](https://github.com/microsoft/playwright-mcp)
2. Open Chrome and go to `chrome://extensions/`
3. Enable "Developer mode" (toggle in top-right)
4. Click "Load unpacked"
5. Select the extension directory

## Step 2: Start the Chrome Extension

1. Click the Playwright MCP extension icon in Chrome toolbar
2. The extension will start a WebSocket server
3. Note the WebSocket URL (usually `ws://localhost:9223/extension`)

## Step 3: Configure Backend

### Environment Variables

Add to your `.env` file in `backend/langgraph/`:

```bash
# Enable Chrome Extension mode
USE_CHROME_EXTENSION=true

# WebSocket URL from Chrome Extension (adjust if different)
CHROME_EXTENSION_WS_URL=ws://localhost:9223/extension
```

### Default Configuration

If `USE_CHROME_EXTENSION` is not set or set to `false`, the backend will use stdio mode (separate browser).

## Step 4: Start Your Backend

```bash
cd backend/langgraph
uvicorn main:app --reload
```

The backend will automatically:
- Use Chrome Extension mode if `USE_CHROME_EXTENSION=true`
- Connect to the Chrome Extension via the WebSocket URL
- Control the user's actual Chrome browser (with session/cookies)

## How It Works

### Chrome Extension Mode Flow:

```
User's Chrome Browser (with session)
    ↓
Playwright MCP Chrome Extension (exposes CDP via WebSocket)
    ↓
Playwright MCP Server (connects via WebSocket)
    ↓
Your FastAPI Backend (via stdio)
    ↓
MCP Node executes actions on user's browser
```

### Benefits:

- ✅ User's session is preserved (logged in, cookies, etc.)
- ✅ Works with private pages (GitHub repos, etc.)
- ✅ Actions happen in user's actual browser
- ✅ No separate browser instance needed

## Testing

### Test with Chrome Extension Mode:

1. Make sure Chrome Extension is running
2. Set `USE_CHROME_EXTENSION=true` in `.env`
3. Send a request with browser keywords:
   ```json
   POST http://localhost:8000/chat
   {
     "user_id": "test",
     "thread_id": "thread1",
     "message": "Navigate to github.com and take a screenshot"
   }
   ```
4. The action should execute in your Chrome browser (not a new one)

### Test with Stdio Mode (Default):

1. Set `USE_CHROME_EXTENSION=false` or remove from `.env`
2. Send the same request
3. Playwright will launch a separate browser instance

## Troubleshooting

### Extension Not Connecting

1. **Check Extension is Running:**
   - Click extension icon in Chrome
   - Verify WebSocket server is active
   - Note the WebSocket URL

2. **Check WebSocket URL:**
   - Default is `ws://localhost:9223/extension`
   - Update `CHROME_EXTENSION_WS_URL` in `.env` if different

3. **Check Backend Logs:**
   - Look for connection errors
   - Verify `USE_CHROME_EXTENSION=true` is set

### Browser Not Responding

1. **Check Chrome Permissions:**
   - Extension needs permission to control browser
   - Check extension settings

2. **Check WebSocket Connection:**
   - Verify extension WebSocket is accessible
   - Test with: `curl http://localhost:9223` (if HTTP endpoint exists)

3. **Check Node.js/npx:**
   - Ensure `npx` is available
   - First run will download `@playwright/mcp` package

## Production Considerations

### For AWS Deployment:

1. **Chrome Extension Mode:**
   - User must have Chrome Extension installed
   - Extension must be running
   - WebSocket must be accessible from backend
   - **Challenge**: Backend and user's browser need to be on same network or use tunneling

2. **Alternative for Production:**
   - Use your existing content script approach (executes in user's browser)
   - Or use Playwright with session injection (export/import cookies)

### Recommended Architecture:

For production, consider:
- **Development**: Use Chrome Extension mode (local testing)
- **Production**: Use content scripts (your current approach) - simpler, no dependencies

## Switching Between Modes

You can easily switch between modes by changing the environment variable:

```bash
# Chrome Extension mode
USE_CHROME_EXTENSION=true

# Stdio mode (default)
USE_CHROME_EXTENSION=false
```

No code changes needed - just restart the server.

