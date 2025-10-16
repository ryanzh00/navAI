// Content script for AI Desktop Assistant
// Handles page content capture and overlay display

import { AssistantMessage, ExtensionMessage, PageContent, ToggleOverlay } from '../types';
import { capturePageData } from './capture';
import { OverlayManager } from './overlay';

console.log('AI Desktop Assistant content script loaded');

// Initialize overlay manager
const overlayManager = new OverlayManager();

// Listen for messages from background script
chrome.runtime.onMessage.addListener((message: ExtensionMessage, _sender, sendResponse) => {
  console.log('Content script received message:', message);
  
  switch (message.type) {
    case 'ASSISTANT_MESSAGE':
      handleAssistantMessage(message as AssistantMessage);
      break;
    
    case 'TOGGLE_OVERLAY':
      handleToggleOverlay(message as ToggleOverlay);
      break;
    
    default:
      console.log('Unknown message type in content script:', message.type);
  }
  
  sendResponse({ success: true });
  return true; // Keep message channel open
});

/**
 * Handle assistant messages and display in overlay
 */
function handleAssistantMessage(message: AssistantMessage) {
  console.log('Displaying assistant message:', message.payload.text);
  overlayManager.show(message.payload.text);
  
  // Auto-hide after 10 seconds
  setTimeout(() => {
    overlayManager.hide();
  }, 10000);
}

/**
 * Handle overlay toggle requests
 */
function handleToggleOverlay(message: ToggleOverlay) {
  if (message.payload.visible) {
    overlayManager.show('Assistant overlay activated');
  } else {
    overlayManager.hide();
  }
}

/**
 * Capture and send page content to background
 */
async function captureAndSendPageContent() {
  try {
    const pageData = capturePageData();
    
    const message: PageContent = {
      type: 'PAGE_CONTENT',
      payload: pageData
    };
    
    await chrome.runtime.sendMessage(message);
    console.log('Page content sent to background');
  } catch (error) {
    console.error('Failed to capture and send page content:', error);
  }
}

// Capture page content when script loads
captureAndSendPageContent();

// Re-capture content when page changes (for SPAs)
let lastUrl = window.location.href;
const observer = new MutationObserver(() => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    setTimeout(captureAndSendPageContent, 1000); // Delay to let page load
  }
});

observer.observe(document.body, {
  childList: true,
  subtree: true
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  overlayManager.destroy();
  observer.disconnect();
});
