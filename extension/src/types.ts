// Shared types for the AI Desktop Assistant extension

export interface Message {
  type: string;
  payload?: any;
}

export interface UserMessage extends Message {
  type: 'USER_MESSAGE';
  payload: {
    text: string;
    agenticMode: boolean;
    tabId?: number; // Optional tab ID from popup
  };
}

export interface AssistantMessage extends Message {
  type: 'ASSISTANT_MESSAGE';
  payload: {
    text: string;
    timestamp: number;
  };
}

export interface PageContent extends Message {
  type: 'PAGE_CONTENT';
  payload: {
    url: string;
    title: string;
    text: string;
    headings: string[];
  };
}

export interface ToggleOverlay extends Message {
  type: 'TOGGLE_OVERLAY';
  payload: {
    visible: boolean;
  };
}

export interface CheckNavaiSpawned extends Message {
  type: 'CHECK_NAVAI_SPAWNED';
  payload?: {};
}

export type ExtensionMessage = UserMessage | AssistantMessage | PageContent | ToggleOverlay | CheckNavaiSpawned;

// Content script types
export interface PageData {
  url: string;
  title: string;
  text: string;
  headings: string[];
}

// Popup state types
export interface PopupState {
  message: string;
  agenticMode: boolean;
  isConnected: boolean;
  conversationHistory: ConversationMessage[];
}

// Conversation message types for popup history
export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;
}
