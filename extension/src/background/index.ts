// Background service worker for AI Desktop Assistant
// Handles message routing between popup and content scripts

import { API_ENDPOINTS, generateId } from '../config';
import { AssistantMessage, ExtensionMessage, UserMessage } from '../types';

console.log('AI Desktop Assistant background script loaded');

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender: chrome.runtime.MessageSender, sendResponse: any) => {
  console.log('Background received message:', message);
  
  switch (message.type) {
    case 'USER_MESSAGE':
      handleUserMessage(message as UserMessage, sender);
      break;
    
    case 'PAGE_CONTENT':
      handlePageContent(message, sender);
      break;
    
    case 'TOGGLE_OVERLAY':
      handleToggleOverlay(message, sender);
      break;
    
    default:
      console.log('Unknown message type:', message.type);
  }
  
  sendResponse({ success: true });
  return true; // Keep message channel open
});

/**
 * Check if a URL is injectable (content scripts can run on it)
 */
function isInjectableUrl(url: string | undefined): boolean {
  if (!url) return false;
  const blockedSchemes = ['chrome:', 'chrome-extension:', 'moz-extension:', 'edge:', 'about:'];
  return !blockedSchemes.some(scheme => url.startsWith(scheme));
}

/**
 * Get or create a user ID (stored in chrome.storage)
 */
async function getOrCreateUserId(): Promise<string> {
  const result = await chrome.storage.local.get(['userId']);
  if (result.userId) {
    return result.userId;
  }
  const userId = generateId();
  await chrome.storage.local.set({ userId });
  return userId;
}

/**
 * Get or create a thread ID (stored in chrome.storage)
 */
async function getOrCreateThreadId(): Promise<string> {
  const result = await chrome.storage.local.get(['threadId']);
  if (result.threadId) {
    return result.threadId;
  }
  const threadId = generateId();
  await chrome.storage.local.set({ threadId });
  return threadId;
}

/**
 * Call backend API for AI processing
 */
async function callBackendAPI(userMessage: string, agenticMode: boolean, pageContent?: any): Promise<string> {
  try {
    // Generate unique IDs for user and thread
    const userId = await getOrCreateUserId();
    const threadId = await getOrCreateThreadId();
    
    const response = await fetch(API_ENDPOINTS.chat, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        thread_id: threadId,
        message: userMessage,
        agentic_mode: agenticMode,
        page_content: pageContent || null,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Backend API error: ${response.status} ${response.statusText} - ${errorText}`);
    }

    const data = await response.json();
    return data.reply || 'No response from backend';
  } catch (error) {
    console.error('Backend API call failed:', error);
    throw error;
  }
}

/**
 * Handle user messages from popup
 */
async function handleUserMessage(message: UserMessage, sender: chrome.runtime.MessageSender) {
  console.log('Processing user message:', message.payload);
  
  let tabID: number | undefined = sender.tab?.id;
  let tabUrl: string | undefined = sender.tab?.url;

  // If no tab ID from sender (e.g., message from popup), get active tab
  if (!tabID) {
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tabs[0]?.id) {
        tabID = tabs[0].id;
        tabUrl = tabs[0].url;
      }
    } catch (error) {
      console.error('Failed to get active tab:', error);
    }
  }

  // Check if we can inject on this URL
  if (!isInjectableUrl(tabUrl)) {
    console.warn('Cannot inject content script on restricted URL:', tabUrl);
    return;
  }

  // Capture page content for non-agentic mode (to use as context)
  let pageContent: any = null;
  if (!message.payload.agenticMode && tabID) {
    try {
      // Request page content from content script
      const pageContentResponse = await chrome.tabs.sendMessage(tabID, { type: 'GET_PAGE_CONTENT' });
      if (pageContentResponse && pageContentResponse.pageData) {
        pageContent = pageContentResponse.pageData;
        console.log('Captured page content for context:', {
          url: pageContent.url,
          title: pageContent.title,
          textLength: pageContent.text?.length || 0
        });
      }
    } catch (error) {
      console.warn('Failed to capture page content:', error);
      // Continue without page content if capture fails
    }
  }

  // Try to call backend API
  let responseText: string;
  try {
    console.log('Calling backend API with agenticMode:', message.payload.agenticMode);
    responseText = await callBackendAPI(message.payload.text, message.payload.agenticMode, pageContent);
    console.log('Received response from backend:', responseText);
  } catch (error) {
    console.error('Backend API failed, using fallback message:', error);
    // Fallback to error message if backend is unavailable
    const errorMsg = error instanceof Error ? error.message : String(error);
    responseText = `Error: Could not connect to backend. ${errorMsg}\n\nMake sure the server is running at ${API_ENDPOINTS.chat}`;
  }
  
  // Create response message
  const assistantResponse: AssistantMessage = {
    type: 'ASSISTANT_MESSAGE',
    payload: {
      text: responseText,
      timestamp: Date.now()
    }
  };

  // Send response to popup (for conversation history - current session only)
  try {
    chrome.runtime.sendMessage(assistantResponse).catch(() => {
      // Popup might not be open, that's okay
    });
  } catch (error) {
    // Ignore errors if popup is not open
  }
  
  // Send response to content script
  if (tabID) {
    try {
      console.log('Sending message to tab:', tabID);
      await chrome.tabs.sendMessage(tabID, assistantResponse);
      console.log('Sent response to content script');
    } catch (error) {
      console.error('Failed to send message to content script:', error);
      // Try to inject content script if it's not loaded
      // Only try if URL is injectable
      if (isInjectableUrl(tabUrl)) {
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tabID },
            files: ['content.js']
          });
          console.log('Injected content script, retrying message...');
          // Wait a bit for script to initialize
          await new Promise(resolve => setTimeout(resolve, 100));
          await chrome.tabs.sendMessage(tabID, assistantResponse);
        } catch (injectError) {
          console.error('Failed to inject content script:', injectError);
        }
      }
    }
  } else {
    console.error('No tab ID found - cannot send message to content script');
  }
}

/**
 * Handle page content from content script
 * TODO: Store page content for context in AI interactions
 */
function handlePageContent(message: ExtensionMessage, _sender: chrome.runtime.MessageSender) {
  console.log('Received page content:', message.payload);
  
  // TODO: Store page content in chrome.storage for context
  // chrome.storage.local.set({ pageContent: message.payload });
}

/**
 * Handle overlay toggle requests
 */
function handleToggleOverlay(message: ExtensionMessage, sender: chrome.runtime.MessageSender) {
  console.log('Toggle overlay:', message.payload);
  
  // Forward to content script
  if (sender.tab?.id) {
    chrome.tabs.sendMessage(sender.tab.id, message);
  }
}

// Extension installation/update handler
chrome.runtime.onInstalled.addListener((details: chrome.runtime.InstalledDetails) => {
  console.log('Extension installed/updated:', details.reason);
  
  // TODO: Initialize default settings
  chrome.storage.local.set({
    agenticMode: false,
    settings: {
      theme: 'light',
      autoCapture: true
    }
  });
});
