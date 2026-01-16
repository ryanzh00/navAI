import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getCurrentTab, sendToBackground } from '../shared/messaging';
import { ConversationMessage, PopupState, UserMessage } from '../types';

const App: React.FC = () => {
  const [state, setState] = useState<PopupState>({
    message: '',
    agenticMode: false,
    isConnected: false,
    conversationHistory: []
  });

  const chatContainerRef = useRef<HTMLDivElement>(null);

  const addMessageToHistory = useCallback((role: 'user' | 'assistant', text: string, timestamp?: number) => {
    const newMessage: ConversationMessage = {
      id: `msg-${Date.now()}-${Math.random()}`,
      role,
      text,
      timestamp: timestamp || Date.now()
    };

    setState((prev: PopupState) => {
      const newHistory = [...prev.conversationHistory, newMessage];
      // Don't save to storage - keep only in current session
      return {
        ...prev,
        conversationHistory: newHistory
      };
    });
  }, []);

  useEffect(() => {
    // Check connection status on mount
    checkConnection();

    // Load saved settings
    loadSettings();

    // Listen for assistant responses from background
    const messageListener = (message: any) => {
      if (message.type === 'ASSISTANT_MESSAGE') {
        addMessageToHistory('assistant', message.payload.text, message.payload.timestamp);
      }
    };

    chrome.runtime.onMessage.addListener(messageListener);

    // Cleanup
    return () => {
      chrome.runtime.onMessage.removeListener(messageListener);
    };
  }, [addMessageToHistory]);

  // Auto-scroll to bottom when new messages are added
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [state.conversationHistory]);

  const checkConnection = async () => {
    try {
      await getCurrentTab();
      setState((prev: PopupState) => ({ ...prev, isConnected: true }));
    } catch (error) {
      console.error('Connection check failed:', error);
      setState((prev: PopupState) => ({ ...prev, isConnected: false }));
    }
  };

  const loadSettings = async () => {
    try {
      const result = await chrome.storage.local.get(['agenticMode']);
      setState((prev: PopupState) => ({
        ...prev,
        agenticMode: result.agenticMode || false
      }));
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  };

  const handleMessageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setState((prev: PopupState) => ({ ...prev, message: e.target.value }));
  };

  const handleAgenticModeToggle = async () => {
    const newMode = !state.agenticMode;
    setState((prev: PopupState) => ({ ...prev, agenticMode: newMode }));

    // Save to storage
    try {
      await chrome.storage.local.set({ agenticMode: newMode });
    } catch (error) {
      console.error('Failed to save agentic mode setting:', error);
    }
  };

  const handleSendMessage = async () => {
    if (!state.message.trim()) return;

    const messageText = state.message.trim();

    try {
      // Add user message to history immediately
      addMessageToHistory('user', messageText);

      const message: UserMessage = {
        type: 'USER_MESSAGE',
        payload: {
          text: messageText,
          agenticMode: state.agenticMode
        }
      };

      console.log('Sending message to background:', message);
      await sendToBackground(message);
      console.log('Message sent to background successfully');

      // Clear input after sending
      setState((prev: PopupState) => ({ ...prev, message: '' }));
    } catch (error) {
      console.error('Failed to send message:', error);
    }
  };

  const clearConversationHistory = () => {
    setState((prev: PopupState) => ({
      ...prev,
      conversationHistory: []
    }));
  };

  const formatTimestamp = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSendMessage();
    }
  };

  return (
    <div className="app">
      <div className="header">
        <h1>navAI</h1>
        {state.conversationHistory.length > 0 && (
          <div className="header-actions">
            <button
              onClick={clearConversationHistory}
              className="clear-button"
              title="Clear conversation"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      <div className="chat-container" ref={chatContainerRef}>
        {state.conversationHistory.length === 0 ? (
          <div className="chat-empty">
            <p>Start a conversation with navAI</p>
          </div>
        ) : (
          state.conversationHistory.map((msg) => (
            <div key={msg.id} className={`chat-message ${msg.role}`}>
              <div className="chat-message-content">
                {msg.text}
              </div>
              <div className="chat-message-time">
                {formatTimestamp(msg.timestamp)}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="controls">
        <label className="toggle-label pretty-toggle">
          <input
            type="checkbox"
            checked={state.agenticMode}
            onChange={handleAgenticModeToggle}
            className="toggle-input"
          />
          <span className="toggle-slider"></span>
          Agentic Mode
        </label>
      </div>

      <div className="input-bar">
        <input
          type="text"
          value={state.message}
          onChange={handleMessageChange}
          onKeyDown={handleKeyPress}
          placeholder="Type a message..."
          className="message-input"
        />
        <button
          onClick={handleSendMessage}
          disabled={!state.message.trim()}
          className="send-button"
        >
          Enter
        </button>
      </div>
    </div>
  );
};

export default App;
