# AI Desktop Assistant Chrome Extension

A Chrome Extension (Manifest V3) with React + TypeScript + Vite for AI-powered web browsing assistance.

## Features

- **Popup UI**: Clean React interface with chat input and Agentic Mode toggle
- **Content Script**: Captures page content and displays AI responses in an overlay
- **Background Service Worker**: Handles message routing between components
- **Message Flow**: Popup → Background → Content Script → Overlay display

## Project Structure

```
extension/
├── src/
│   ├── background/
│   │   └── index.ts          # Service worker for message routing
│   ├── content/
│   │   ├── capture.ts        # Page content extraction
│   │   ├── overlay.tsx       # React overlay component
│   │   └── index.ts          # Content script entry point
│   ├── popup/
│   │   ├── App.tsx           # Main popup React component
│   │   ├── App.css           # Popup styles
│   │   └── main.tsx          # Popup entry point
│   ├── shared/
│   │   └── messaging.ts      # Chrome extension messaging utilities
│   └── types.ts              # Shared TypeScript types
├── manifest.json             # Chrome extension manifest
├── popup.html                # Popup HTML template
├── vite.config.ts            # Vite build configuration
└── package.json              # Dependencies and scripts
```

## Development

1. **Install dependencies**:
   ```bash
   cd extension
   npm install
   ```

2. **Build the extension**:
   ```bash
   npm run build
   ```

3. **Load in Chrome**:
   - Open Chrome and go to `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked" and select the `extension/dist` folder

## Message Flow

1. User types message in popup → `USER_MESSAGE` sent to background
2. Background processes message → `ASSISTANT_MESSAGE` sent to content script
3. Content script displays response in overlay

## TODO: Backend Integration

The extension is ready for backend integration. Key integration points:

- **Background script**: Replace mock response in `handleUserMessage()` with actual API calls
- **Content script**: Enhance page content capture for better context
- **Popup**: Add conversation history and better UX

## Current Behavior

- Popup shows connection status and Agentic Mode toggle
- Typing a message and pressing Enter sends it to the background
- Background responds with "Assistant: Hello world!" mock message
- Content script displays the response in a styled overlay (bottom-right corner)
- Overlay auto-hides after 10 seconds

## Next Steps

1. Set up Node.js backend with AI API integration
2. Implement real message persistence
3. Add conversation history in popup
4. Enhance page content analysis
5. Add more sophisticated overlay interactions
