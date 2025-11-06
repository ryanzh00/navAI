// Shared messaging utilities for Chrome extension communication

import { ExtensionMessage } from '../types';

/**
 * Send message to background script
 */
export const sendToBackground = (message: ExtensionMessage): Promise<any> => {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response: any) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(response);
      }
    });
  });
};

/**
 * Send message to content script
 */
export const sendToContentScript = (tabId: number, message: ExtensionMessage): Promise<any> => {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response: any) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(response);
      }
    });
  });
};

/**
 * Listen for messages from other parts of the extension
 */
export const addMessageListener = (callback: (message: ExtensionMessage, sender: chrome.runtime.MessageSender) => void) => {
  chrome.runtime.onMessage.addListener((message: any, sender: chrome.runtime.MessageSender, sendResponse: any) => {
    callback(message, sender);
    sendResponse({ success: true });
    return true; // Keep message channel open for async response
  });
};

/**
 * Get current active tab
 */
export const getCurrentTab = (): Promise<chrome.tabs.Tab> => {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs: chrome.tabs.Tab[]) => {
      if (tabs[0]) {
        resolve(tabs[0]);
      } else {
        reject(new Error('No active tab found'));
      }
    });
  });
};
