import React, { useEffect, useState } from 'react';
import { getCurrentTab, sendToBackground } from '../shared/messaging';
import { PopupState, UserMessage } from '../types';

const App: React.FC = () => {
  const [state, setState] = useState<PopupState>({
    message: '',
    agenticMode: false,
    isConnected: false
  });

  useEffect(() => {
    // Check connection status on mount
    checkConnection();

    // Load saved settings
    loadSettings();
  }, []);

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

    try {
      const message: UserMessage = {
        type: 'USER_MESSAGE',
        payload: {
          text: state.message.trim(),
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

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSendMessage();
    }
  };

  return (
    <div className="app">
      <div className="header">
        <h1>navAI</h1>
      </div>

      <div className="chat-container">
        {state.message && (
          <div className="chat-message user">
            {state.message}
          </div>
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
