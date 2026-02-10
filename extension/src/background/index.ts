// Background service worker for AI Desktop Assistant
// Handles message routing between popup and content scripts

import { API_ENDPOINTS } from '../config';
import { AssistantMessage, ExtensionMessage, UserMessage } from '../types';

console.log('AI Desktop Assistant background script loaded');

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender: chrome.runtime.MessageSender, sendResponse: any) => {
  console.log('Background received message:', message);
  
  switch (message.type) {
    case 'USER_MESSAGE':
      // Handle async function properly - wrap in promise
      handleUserMessage(message as UserMessage, sender).catch((error) => {
        console.error('Error in handleUserMessage:', error);
      });
      break;
    
    case 'PAGE_CONTENT':
      handlePageContent(message, sender);
      break;
    
    case 'TOGGLE_OVERLAY':
      handleToggleOverlay(message, sender);
      break;
    
    case 'CHECK_NAVAI_SPAWNED':
      // Check if current tab has navai_spawned flag in localStorage
      // Popup doesn't have sender.tab, so we need to get the active tab
      (async () => {
        try {
          // Get the active tab (popup context doesn't have sender.tab)
          const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
          const tabId = tabs[0]?.id;
          const result = await checkNavaiSpawned(tabId);
          sendResponse({ success: true, isNavaiSpawned: result });
        } catch (error) {
          console.error('Error checking navai_spawned:', error);
          sendResponse({ success: false, isNavaiSpawned: false });
        }
      })();
      return true; // Keep channel open for async response
    
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
 * Get tab index (0-based position in the tab bar) for a given tab ID
 */
async function getTabIndex(tabId: number): Promise<number | null> {
  try {
    // Get all tabs in the current window
    const tabs = await chrome.tabs.query({ currentWindow: true });
    // Find the index of the tab with the given ID
    const index = tabs.findIndex(tab => tab.id === tabId);
    if (index !== -1) {
      return index;
    }
    return null;
  } catch (error) {
    console.error('Failed to get tab index:', error);
    return null;
  }
}

/**
 * Call backend API for AI processing
 */
async function callBackendAPI(userMessage: string, agenticMode: boolean, pageContent?: any, tabIndex?: number | null): Promise<string> {
  console.log('[API] Starting API call to:', API_ENDPOINTS.chat);
  console.log('[API] Request body:', { message: userMessage, agentic_mode: agenticMode, page_content: !!pageContent, tab_index: tabIndex });
  
  try {
    const requestBody: any = {
      message: userMessage,
      agentic_mode: agenticMode,
      page_content: pageContent || null,
    };
    
    // Add tab_index if provided (for selecting correct tab in Playwright browser)
    if (tabIndex !== null && tabIndex !== undefined) {
      requestBody.tab_index = tabIndex;
    }
    
    console.log('[API] Sending request to:', API_ENDPOINTS.chat);
    const response = await fetch(API_ENDPOINTS.chat, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody),
    });

    console.log('[API] Response status:', response.status, response.statusText);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('[API] Error response:', errorText);
      throw new Error(`Backend API error: ${response.status} ${response.statusText} - ${errorText}`);
    }

    const data = await response.json();
    console.log('[API] Success - received reply:', data.reply?.substring(0, 100));
    return data.reply || 'No response from backend';
  } catch (error) {
    console.error('[API] Backend API call failed:', error);
    if (error instanceof TypeError && error.message.includes('fetch')) {
      console.error('[API] Network error - is the backend server running at', API_ENDPOINTS.chat, '?');
    }
    throw error;
  }
}

/**
 * Handle user messages from popup
 */
async function handleUserMessage(message: UserMessage, sender: chrome.runtime.MessageSender) {
  console.log('[handleUserMessage] Starting - Processing user message:', message.payload);
  console.log('[handleUserMessage] Sender:', { tabId: sender.tab?.id, url: sender.tab?.url });
  
  let tabID: number | undefined = sender.tab?.id;
  let tabUrl: string | undefined = sender.tab?.url;

  // Priority: 1) Tab ID from message payload (from popup), 2) Tab ID from sender, 3) Query for active tab
  if (message.payload.tabId) {
    // Use tab ID provided by popup (most reliable for popup messages)
    tabID = message.payload.tabId;
    try {
      const tab = await chrome.tabs.get(tabID);
      tabUrl = tab.url;
      console.log('Using tab ID from popup message:', { tabID, tabUrl });
    } catch (error) {
      console.error('Failed to get tab info for provided tab ID:', error);
      // Fall back to querying
      tabID = undefined;
    }
  }
  
  // If still no tab ID, try sender's tab (from content script)
  if (!tabID && sender.tab?.id) {
    tabID = sender.tab.id;
    tabUrl = sender.tab.url;
    console.log('Using sender tab:', { tabID, tabUrl });
  }
  
  // If still no tab ID, query for active tab (fallback)
  if (!tabID) {
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tabs[0]?.id) {
        tabID = tabs[0].id;
        tabUrl = tabs[0].url;
        console.log('Got active tab via query:', { tabID, tabUrl });
      } else {
        console.warn('No active tab found');
      }
    } catch (error) {
      console.error('Failed to get active tab:', error);
    }
  }

  // Capture page content for non-agentic mode (to use as context)
  // Only try if the URL is injectable (we can run content scripts)
  let pageContent: any = null;
  if (!message.payload.agenticMode && tabID && isInjectableUrl(tabUrl)) {
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
      console.warn('Failed to capture page content (content script may not be loaded):', error);
      // Continue without page content if capture fails
      // This is OK - we can still call the API without page content
    }
  } else if (!isInjectableUrl(tabUrl)) {
    console.warn('Cannot inject content script on restricted URL:', tabUrl, '- continuing without page content');
  }

  // Get tab index for Playwright browser tab selection (0-based position in tab bar)
  let tabIndex: number | null = null;
  if (tabID) {
    tabIndex = await getTabIndex(tabID);
    console.log(`Tab ID ${tabID} corresponds to tab index ${tabIndex}`);
  }

  // Always call backend API - even if we couldn't get page content or inject scripts
  let responseText: string;
  try {
    console.log('Calling backend API with agenticMode:', message.payload.agenticMode, 'pageContent:', !!pageContent, 'tabIndex:', tabIndex);
    responseText = await callBackendAPI(message.payload.text, message.payload.agenticMode, pageContent, tabIndex);
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
  // IMPORTANT: chrome.runtime.sendMessage is callback-based in many Chrome builds and may not return a Promise.
  // Using `.catch` here can throw and prevent the popup chat from receiving the message.
  try {
    chrome.runtime.sendMessage(assistantResponse, () => {
      // It's normal for this to fail if the popup isn't open.
      const err = chrome.runtime.lastError;
      if (err) {
        // Keep this quiet; content-script delivery still works.
        console.debug('Popup not available for ASSISTANT_MESSAGE:', err.message);
      }
    });
  } catch (error) {
    // Ignore errors if popup is not open / context not available
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

/**
 * Check if current tab has navai_spawned flag in localStorage
 */
async function checkNavaiSpawned(tabId: number | undefined): Promise<boolean> {
  if (!tabId) {
    // Try to get the active tab
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tabs[0]?.id) {
        tabId = tabs[0].id;
      } else {
        return false;
      }
    } catch (error) {
      console.error('Failed to get active tab:', error);
      return false;
    }
  }

  try {
    // Check if URL is injectable
    const tab = await chrome.tabs.get(tabId);
    if (!tab.url || !isInjectableUrl(tab.url)) {
      return false;
    }

    // Execute script to check localStorage
    const results = await chrome.scripting.executeScript({
      target: { tabId: tabId },
      func: () => {
        try {
          return localStorage.getItem('navai_spawned') === 'true';
        } catch (error) {
          return false;
        }
      }
    });

    if (results && results[0] && results[0].result) {
      return results[0].result === true;
    }
    return false;
  } catch (error) {
    console.error('Failed to check navai_spawned:', error);
    return false;
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
