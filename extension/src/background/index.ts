// Background service worker for AI Desktop Assistant
// Handles message routing between popup and content scripts

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
 * Handle user messages from popup
 * TODO: Integrate with backend API for AI processing
 */
async function handleUserMessage(message: UserMessage, sender: chrome.runtime.MessageSender) {
  console.log('Processing user message:', message.payload);
  
  // TODO: Send to backend API for AI processing
  // const aiResponse = await callBackendAPI(message.payload);
  
  // For now, create a mock response
  const mockResponse: AssistantMessage = {
    type: 'ASSISTANT_MESSAGE',
    payload: {
      text: 'Assistant: Hello world! This is a mock response.',
      timestamp: Date.now()
    }
  };

  let tabID: number|undefined = sender.tab?.id;

  if (!tabID) {
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      if (tabs[0]?.id) {
        tabID = tabs[0].id;
      }
    } catch (error) {
      console.error('Failed to get active tab:', error);
    }
  
  }
  
  // Send response to content script
  if (tabID) {
    try {
      console.log('Sending message to tab:', tabID);
      await chrome.tabs.sendMessage(tabID, mockResponse);
      console.log('Sent response to content script');
    } catch (error) {
      console.error('Failed to send message to content script:', error);
      // Try to inject content script if it's not loaded
      try {
        await chrome.scripting.executeScript({
          target: { tabId: tabID },
          files: ['content.js']
        });
        console.log('Injected content script, retrying message...');
        await chrome.tabs.sendMessage(tabID, mockResponse);
      } catch (injectError) {
        console.error('Failed to inject content script:', injectError);
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
