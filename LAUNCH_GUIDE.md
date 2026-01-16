# navAI Launch Guide

This guide explains how to launch both the backend server and the Chrome extension.

## Project Overview

**navAI** is an AI-powered browser assistant with:
- **Backend**: FastAPI server with LangGraph, Playwright MCP, and ChromaDB for memory
- **Extension**: Chrome extension (Manifest V3) with React + TypeScript

## Prerequisites

### Backend Requirements
- Python 3.11+
- Node.js and npm (for Playwright MCP)
- OpenAI API key

### Extension Requirements
- Node.js and npm
- Chrome browser

## Step 1: Backend Setup

### 1.1 Navigate to Backend Directory
```bash
cd backend/langgraph
```

### 1.2 Activate Virtual Environment
The project includes a virtual environment at `backend/langgraph/env/`:

**macOS/Linux:**
```bash
source env/bin/activate
```

**Windows:**
```bash
env\Scripts\activate
```

### 1.3 Install Dependencies (if needed)
If dependencies aren't installed:
```bash
pip install -r requirements.txt
```

### 1.4 Set Up Environment Variables
Create a `.env` file in `backend/langgraph/` (if it doesn't exist):

```bash
# Required: OpenAI API Key
OPENAI_API_KEY=your_openai_api_key_here

# Optional: Chrome Extension Mode (for Playwright MCP)
# Set to true to use Chrome Extension mode (connects to user's Chrome)
# Set to false or omit to use stdio mode (launches separate browser)
USE_CHROME_EXTENSION=false

# Optional: Chrome Extension WebSocket URL (if using Chrome Extension mode)
CHROME_EXTENSION_WS_URL=ws://localhost:9223/extension

# Optional: Override npm/npx path (defaults to /opt/homebrew/bin/npx on macOS)
# NPM_BIN=/usr/local/bin/npx
```

### 1.5 Launch Backend Server
```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

**Note:** Avoid using `--reload` if you want the browser window to persist between edits, as reload restarts the process and closes the MCP browser.

The server will:
- Start on `http://localhost:8000`
- Initialize ChromaDB for memory storage
- Connect to Playwright MCP (launches a browser window)
- Navigate to Google.com automatically

### 1.6 Verify Backend is Running
- Check terminal for: `[DEBUG] Loaded X tools from session`
- A browser window should open automatically
- Test endpoint: `curl http://localhost:8000/debug/mcp-snapshot`

## Step 2: Extension Setup

### 2.1 Navigate to Extension Directory
```bash
cd extension
```

### 2.2 Install Dependencies
```bash
npm install
```

### 2.3 Build the Extension
```bash
npm run build
```

This will:
- Compile TypeScript to JavaScript
- Bundle with Vite
- Copy files to `dist/` directory

### 2.4 Load Extension in Chrome

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in top-right corner)
3. Click **"Load unpacked"**
4. Select the `extension/dist` folder (not the `extension` folder)

### 2.5 Verify Extension is Loaded
- Extension icon should appear in Chrome toolbar
- Click the icon to open the popup
- You should see "navAI" interface with:
  - Connection status
  - Agentic Mode toggle
  - Message input field

## Step 3: Connect Extension to Backend

### 3.1 Update Backend URL (if needed)
The extension is configured to connect to `http://localhost:8000` by default.

To change this, edit `extension/src/config.ts`:
```typescript
export const BACKEND_URL = 'http://localhost:8000';
```

### 3.2 Test Connection
1. Make sure backend is running (Step 1)
2. Open extension popup
3. Type a message and press Enter
4. You should see a response in the overlay on the current page

**Note:** Currently, the extension uses mock responses. To integrate with the backend, update `extension/src/background/index.ts` to call the API.

## Step 4: Using the System

### Backend API Endpoints

**Chat Endpoint:**
```bash
POST http://localhost:8000/chat
Content-Type: application/json

{
  "user_id": "test",
  "thread_id": "thread1",
  "message": "Navigate to github.com and take a screenshot"
}
```

**Debug Snapshot:**
```bash
POST http://localhost:8000/debug/mcp-snapshot
```

**Open Browser:**
```bash
POST http://localhost:8000/open
```

### Extension Features

- **Popup UI**: Chat interface with Agentic Mode toggle
- **Content Script**: Captures page content automatically
- **Overlay**: Displays AI responses in bottom-right corner
- **Message Flow**: Popup → Background → Content Script → Overlay

### Browser Automation

The backend uses Playwright MCP for browser automation. It can:
- Navigate to URLs
- Take screenshots
- Click buttons
- Fill forms
- Interact with page elements

Keywords that trigger browser automation:
- "click", "navigate", "browser", "page", "website"
- "screenshot", "scrape", "automate", "interact"
- "button", "form", "fill", "submit"
- "github", "login", "logout", "type", "select"

## Troubleshooting

### Backend Issues

**Browser doesn't open:**
- Check that `npx` is available: `which npx`
- Verify Node.js is installed: `node --version`
- Check terminal for MCP connection errors

**MCP connection fails:**
- Ensure `@playwright/mcp` can be downloaded (first run downloads it)
- Check network connectivity
- Verify npm/npx path in `.env` if needed

**OpenAI API errors:**
- Verify `OPENAI_API_KEY` is set in `.env`
- Check API key is valid and has credits

**Port already in use:**
- Change port: `uvicorn main:app --port 8001`
- Update extension config to match new port

### Extension Issues

**Build fails:**
- Run `npm install` first
- Check Node.js version (should be 16+)
- Clear `node_modules` and reinstall: `rm -rf node_modules && npm install`

**Extension won't load:**
- Ensure you selected the `dist/` folder, not `src/` or root
- Check browser console for errors: `chrome://extensions/` → Extension details → Errors
- Verify all files are in `dist/` folder

**Messages not working:**
- Check extension permissions in `manifest.json`
- Verify content script is injected (check page console)
- Check background script console: `chrome://extensions/` → Service worker

**No overlay appears:**
- Check page console for errors
- Verify content script is loaded
- Try refreshing the page

### Chrome Extension Mode (Advanced)

To use Chrome Extension mode (connects to your actual Chrome browser):

1. Install Playwright MCP Chrome Extension:
   - From Chrome Web Store: [Browser MCP](https://chromewebstore.google.com/detail/browser-mcp-automate-your/bjfgambnhccakkhmkepdoekmckoijdlc)
   - Or load from GitHub: [Playwright MCP Extension](https://github.com/microsoft/playwright-mcp)

2. Start the Chrome Extension:
   - Click the Playwright MCP extension icon
   - Note the WebSocket URL (usually `ws://localhost:9223/extension`)

3. Update `.env`:
   ```bash
   USE_CHROME_EXTENSION=true
   CHROME_EXTENSION_WS_URL=ws://localhost:9223/extension
   ```

4. Restart backend server

This mode preserves your Chrome session, cookies, and logged-in state.

## Development Workflow

### Backend Development
```bash
cd backend/langgraph
source env/bin/activate  # or env\Scripts\activate on Windows
uvicorn main:app --reload  # Use --reload for auto-restart on changes
```

### Extension Development
```bash
cd extension
npm run dev  # Watch mode (if configured)
npm run build  # Build for testing
```

After building, reload the extension in Chrome:
1. Go to `chrome://extensions/`
2. Click reload icon on the extension card

## Project Structure

```
navAI/
├── backend/
│   └── langgraph/
│       ├── main.py              # FastAPI server + LangGraph
│       ├── requirements.txt     # Python dependencies
│       ├── .env                 # Environment variables (create this)
│       ├── memory.sqlite        # Conversation memory
│       ├── chroma/              # Vector store for long-term memory
│       └── mcp_data/            # Playwright browser data
│
├── extension/
│   ├── src/
│   │   ├── background/          # Service worker
│   │   ├── content/             # Content scripts
│   │   ├── popup/               # React popup UI
│   │   ├── shared/              # Shared utilities
│   │   ├── config.ts            # Backend URL config
│   │   └── types.ts             # TypeScript types
│   ├── dist/                    # Built extension (load this in Chrome)
│   ├── package.json
│   └── manifest.json
│
└── LAUNCH_GUIDE.md              # This file
```

## Next Steps

1. **Integrate Extension with Backend**: Update `extension/src/background/index.ts` to call `/chat` endpoint
2. **Add Conversation History**: Store and display chat history in popup
3. **Enhanced Page Analysis**: Improve content capture for better context
4. **Error Handling**: Add better error messages and retry logic
5. **Authentication**: Add user authentication if needed

## Quick Start Summary

```bash
# Terminal 1: Backend
cd backend/langgraph
source env/bin/activate
# Create .env with OPENAI_API_KEY
uvicorn main:app --host 127.0.0.1 --port 8000

# Terminal 2: Extension
cd extension
npm install
npm run build
# Then load extension/dist in Chrome
```

That's it! The system should now be running.

