import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getCurrentTab, sendToBackground } from '../shared/messaging';
import { ConversationMessage, PopupState, UserMessage } from '../types';
import { API_ENDPOINTS } from '../config';

const App: React.FC = () => {
  const [state, setState] = useState<PopupState>({
    message: '',
    agenticMode: false,
    isConnected: false,
    conversationHistory: []
  });
  const [isNavaiSpawned, setIsNavaiSpawned] = useState<boolean | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [currentView, setCurrentView] = useState<'chat' | 'profile'>('chat');
  const [userInfo, setUserInfo] = useState({
    first_name: '',
    last_name: '',
    date_of_birth: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    state: '',
    zip_code: '',
    country: '',
    timezone: '',
    additional_info: '',
  });
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const isRecordingRef = useRef(false);

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
      // Save to storage for persistence
      chrome.storage.local.set({ conversationHistory: newHistory }).catch((error) => {
        console.error('Failed to save conversation history:', error);
      });
      return {
        ...prev,
        conversationHistory: newHistory
      };
    });
  }, []);

  useEffect(() => {
    // Check connection status on mount
    checkConnection();
    
    // Check if current tab is navAI spawned
    checkNavaiSpawned();

    // Load saved settings immediately
    loadSettings().then(() => {
      console.log('Settings loaded, current agenticMode:', state.agenticMode);
    });

    // Listen for assistant responses from background
    const messageListener = (message: any) => {
      if (message.type === 'ASSISTANT_MESSAGE') {
        addMessageToHistory('assistant', message.payload.text, message.payload.timestamp);
      }
      if (message.type === 'SPEECH_TRANSCRIPT') {
        setState(prev => ({ ...prev, message: prev.message + message.text }));
      }
      if (message.type === 'SPEECH_RECOGNITION_ENDED' || message.type === 'SPEECH_RECOGNITION_ERROR') {
        isRecordingRef.current = false;
        setIsRecording(false);
      }
    };

    chrome.runtime.onMessage.addListener(messageListener);

    // Listen for tab activation changes to re-check navAI spawned status
    const handleTabActivated = () => {
      console.log('Tab activated, re-checking navAI spawned status');
      // Small delay to ensure tab is fully loaded
      setTimeout(() => {
        checkNavaiSpawned();
      }, 100);
    };

    // Listen for tab updates (when tab finishes loading) to re-check
    const handleTabUpdated = (tabId: number, changeInfo: chrome.tabs.TabChangeInfo) => {
      // Only check if the updated tab is the active tab and it just finished loading
      if (changeInfo.status === 'complete') {
        chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => {
          if (tabs[0]?.id === tabId) {
            console.log('Active tab finished loading, re-checking navAI spawned status');
            setTimeout(() => {
              checkNavaiSpawned();
            }, 100);
          }
        });
      }
    };

    chrome.tabs.onActivated.addListener(handleTabActivated);
    chrome.tabs.onUpdated.addListener(handleTabUpdated);

    // Cleanup
    return () => {
      chrome.runtime.onMessage.removeListener(messageListener);
      chrome.tabs.onActivated.removeListener(handleTabActivated);
      chrome.tabs.onUpdated.removeListener(handleTabUpdated);
    };
  }, [addMessageToHistory]);

  // Load user profile when profile view is opened
  useEffect(() => {
    if (isNavaiSpawned && currentView === 'profile') {
      loadUserProfile();
    }
  }, [currentView, isNavaiSpawned]);

  const checkNavaiSpawned = async () => {
    setIsLoading(true);
    try {
      // Get the active tab
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabId = tabs[0]?.id;
      
      if (!tabId) {
        console.warn('No active tab found');
        setIsNavaiSpawned(false);
        return;
      }

      // Check if we can inject into this tab
      const tab = await chrome.tabs.get(tabId);
      
      // If tab URL is restricted (chrome://, chrome-extension://), we can't check
      // Just return false silently - the tab update listener will re-check when URL changes
      if (!tab.url || tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
        console.log('Skipping check for restricted URL:', tab.url, '- will check again when tab navigates');
        setIsNavaiSpawned(false);
        return;
      }

      // Execute script to check localStorage directly
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

      const isSpawned = results && results[0] && results[0].result === true;
      setIsNavaiSpawned(isSpawned);
      console.log('navAI spawned check result:', isSpawned);
    } catch (error) {
      console.error('Failed to check navAI spawned:', error);
      setIsNavaiSpawned(false);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLaunch = async () => {
    try {
      // Call backend to ensure Playwright browser is ready
      await fetch(API_ENDPOINTS.openBrowser, { method: 'POST' });
      
      // Navigate current tab to a default URL (Playwright browser will be launched)
      const currentTab = await getCurrentTab();
      if (currentTab.id) {
        chrome.tabs.update(currentTab.id, { url: 'https://www.google.com' });
      }
      
      // Re-check after a short delay
      setTimeout(() => {
        checkNavaiSpawned();
      }, 2000);
    } catch (error) {
      console.error('Failed to launch browser:', error);
    }
  };

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
      const result = await chrome.storage.local.get(['agenticMode', 'conversationHistory']);
      const agenticMode = result.agenticMode !== undefined ? result.agenticMode : false;
      console.log('Loaded settings - agenticMode:', agenticMode, 'from storage:', result.agenticMode);
      setState((prev: PopupState) => ({
        ...prev,
        agenticMode: agenticMode,
        conversationHistory: (result.conversationHistory as ConversationMessage[]) || []
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
    console.log('Toggling agentic mode from', state.agenticMode, 'to', newMode);
    setState((prev: PopupState) => ({ ...prev, agenticMode: newMode }));

    // Save to storage
    try {
      await chrome.storage.local.set({ agenticMode: newMode });
      console.log('Saved agenticMode to storage:', newMode);
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

      // Double-check agenticMode from storage to ensure we have the latest value
      const storageResult = await chrome.storage.local.get(['agenticMode']);
      const currentAgenticMode = storageResult.agenticMode !== undefined ? storageResult.agenticMode : state.agenticMode;
      
      // Get the current active tab to ensure we're working with the right tab
      let currentTabId: number | undefined;
      try {
        const currentTab = await getCurrentTab();
        currentTabId = currentTab.id;
        console.log('Popup: Got active tab ID:', currentTabId, 'URL:', currentTab.url);
      } catch (error) {
        console.warn('Popup: Failed to get current tab:', error);
      }
      
      console.log('Current state.agenticMode:', state.agenticMode);
      console.log('Storage agenticMode:', storageResult.agenticMode);
      console.log('Using agenticMode:', currentAgenticMode);
      console.log('Current tab ID from popup:', currentTabId);

      const message: UserMessage = {
        type: 'USER_MESSAGE',
        payload: {
          text: messageText,
          agenticMode: currentAgenticMode,
          tabId: currentTabId
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
    // Clear from storage as well
    chrome.storage.local.remove('conversationHistory').catch((error) => {
      console.error('Failed to clear conversation history from storage:', error);
    });
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

  const loadUserProfile = async () => {
    try {
      console.log('Loading user profile...');
      const response = await fetch(API_ENDPOINTS.getUserInfo);
      if (response.ok) {
        const data = await response.json();
        const retrieved_user_info = data.user_info || {};
        console.log('Profile data received:', data);
        // Set userInfo with saved data (this will pre-fill the inputs with actual values)
        setUserInfo({
          first_name: retrieved_user_info.first_name || '',
          last_name: retrieved_user_info.last_name || '',
          date_of_birth: retrieved_user_info.date_of_birth || '',
          email: retrieved_user_info.email || '',
          phone: retrieved_user_info.phone || '',
          address: retrieved_user_info.address || '',
          city: retrieved_user_info.city || '',
          state: retrieved_user_info.state || '',
          zip_code: retrieved_user_info.zip_code || '',
          country: retrieved_user_info.country || '',
          timezone: retrieved_user_info.timezone || '',
          additional_info: retrieved_user_info.additional_info || '',
        });
        console.log('Profile state updated');
      } else {
        console.error('Failed to load profile, response not ok:', response.status);
      }
    } catch (error) {
      console.error('Failed to load user profile:', error);
    }
  };

  const handleProfileClick = () => {
    setCurrentView('profile');
    // Load profile immediately when profile button is clicked
    if (isNavaiSpawned) {
      loadUserProfile();
    }
  };

  const handleProfileFieldChange = (field: string, value: string) => {
    setUserInfo((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveProfile = async () => {
    setIsSavingProfile(true);
    try {
      // Send all userInfo fields (which now contain the actual values from database or user edits)
      const response = await fetch(API_ENDPOINTS.updateUserInfo, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(userInfo),
      });

      if (response.ok) {
        const data = await response.json();
        console.log('Profile saved successfully:', data);
        // Reload profile to refresh the data
        await loadUserProfile();
        // Go back to chat
        setCurrentView('chat');
      } else {
        console.error('Failed to save profile');
      }
    } catch (error) {
      console.error('Error saving profile:', error);
    } finally {
      setIsSavingProfile(false);
    }
  };

  const handleToggleRecording = async () => {
    // If currently recording, stop by sending a message to the content page
    if (isRecording) {
      isRecordingRef.current = false;
      setIsRecording(false);
      try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const tabId = tabs[0]?.id;
        if (tabId) {
          await chrome.tabs.sendMessage(tabId, { type: 'STOP_SPEECH_RECOGNITION' });
        }
      } catch (e) {
        console.error('Failed to stop speech recognition:', e);
      }
      return;
    }

    // Start recording by injecting speech recognition into the active tab
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tabId = tabs[0]?.id;
      if (!tabId) {
        console.error('No active tab found for speech recognition.');
        return;
      }

      // Inject the speech recognition script into the page
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          // If already running, stop first
          if ((window as any).__navai_recognition) {
            (window as any).__navai_recognition.stop();
            (window as any).__navai_recognition = null;
          }

          const SpeechRecognitionCtor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
          if (!SpeechRecognitionCtor) {
            chrome.runtime.sendMessage({ type: 'SPEECH_RECOGNITION_ERROR', error: 'not-supported' });
            return;
          }

          const recognition = new SpeechRecognitionCtor();
          recognition.continuous = true;
          recognition.interimResults = true;
          recognition.lang = 'en-US';

          (window as any).__navai_recognition = recognition;

          recognition.onresult = (event: any) => {
            let finalTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
              if (event.results[i].isFinal) {
                finalTranscript += event.results[i][0].transcript;
              }
            }
            if (finalTranscript) {
              chrome.runtime.sendMessage({ type: 'SPEECH_TRANSCRIPT', text: finalTranscript });
            }
          };

          recognition.onerror = (event: any) => {
            console.error('Speech recognition error:', event.error);
            if (event.error !== 'aborted' && event.error !== 'no-speech') {
              chrome.runtime.sendMessage({ type: 'SPEECH_RECOGNITION_ENDED' });
              (window as any).__navai_recognition = null;
            }
          };

          recognition.onend = () => {
            // Only send ended if we're not restarting
            if (!(window as any).__navai_recognition) return;
            // Try to restart to keep listening
            try {
              recognition.start();
            } catch (e) {
              chrome.runtime.sendMessage({ type: 'SPEECH_RECOGNITION_ENDED' });
              (window as any).__navai_recognition = null;
            }
          };

          // Listen for stop messages from the popup
          const stopListener = (message: any) => {
            if (message.type === 'STOP_SPEECH_RECOGNITION') {
              (window as any).__navai_recognition = null;
              recognition.stop();
              chrome.runtime.onMessage.removeListener(stopListener);
              chrome.runtime.sendMessage({ type: 'SPEECH_RECOGNITION_ENDED' });
            }
          };
          chrome.runtime.onMessage.addListener(stopListener);

          try {
            recognition.start();
          } catch (e) {
            chrome.runtime.sendMessage({ type: 'SPEECH_RECOGNITION_ERROR', error: 'start-failed' });
            (window as any).__navai_recognition = null;
          }
        }
      });

      isRecordingRef.current = true;
      setIsRecording(true);
    } catch (e) {
      console.error('Failed to start speech recognition:', e);
      isRecordingRef.current = false;
      setIsRecording(false);
    }
  };

  // Show loading state
  if (isLoading) {
    return (
      <div className="app">
        <div className="header">
          <h1>navAI</h1>
        </div>
        <div className="chat-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  // Show launch button if not on navAI spawned browser
  if (!isNavaiSpawned) {
    return (
      <div className="app">
        <div className="header">
          <h1>navAI</h1>
        </div>
        <div className="chat-container" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '300px', padding: '20px', textAlign: 'center' }}>
          <p style={{ marginBottom: '20px', color: '#666' }}>
            Open the assisted browser to start chatting with navAI
          </p>
          <button
            onClick={handleLaunch}
            className="send-button"
            style={{ padding: '12px 24px', fontSize: '16px', fontWeight: 'bold' }}
          >
            Launch
          </button>
        </div>
      </div>
    );
  }

  // Show chat interface if on navAI spawned browser
  if (currentView === 'profile') {
    return (
      <div className="app">
        <div className="header">
          <h1>navAI</h1>
          <div className="header-actions">
            <button
              onClick={() => setCurrentView('chat')}
              className="clear-button"
              title="Back to chat"
            >
              Back
            </button>
          </div>
        </div>

        <div className="chat-container" style={{ padding: '20px', overflowY: 'auto' }}>
          <h2 style={{ marginBottom: '20px', fontSize: '18px', fontWeight: 'bold' }}>Profile Information</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>First Name</label>
              <input
                type="text"
                value={userInfo.first_name}
                onChange={(e) => handleProfileFieldChange('first_name', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Last Name</label>
              <input
                type="text"
                value={userInfo.last_name}
                onChange={(e) => handleProfileFieldChange('last_name', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Date of Birth</label>
              <input
                type="date"
                value={userInfo.date_of_birth}
                onChange={(e) => handleProfileFieldChange('date_of_birth', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Email</label>
              <input
                type="email"
                value={userInfo.email}
                onChange={(e) => handleProfileFieldChange('email', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Phone</label>
              <input
                type="tel"
                value={userInfo.phone}
                onChange={(e) => handleProfileFieldChange('phone', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Address</label>
              <input
                type="text"
                value={userInfo.address}
                onChange={(e) => handleProfileFieldChange('address', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>City</label>
              <input
                type="text"
                value={userInfo.city}
                onChange={(e) => handleProfileFieldChange('city', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>State</label>
              <input
                type="text"
                value={userInfo.state}
                onChange={(e) => handleProfileFieldChange('state', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Zip Code</label>
              <input
                type="text"
                value={userInfo.zip_code}
                onChange={(e) => handleProfileFieldChange('zip_code', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Country</label>
              <input
                type="text"
                value={userInfo.country}
                onChange={(e) => handleProfileFieldChange('country', e.target.value)}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Timezone</label>
              <input
                type="text"
                value={userInfo.timezone}
                onChange={(e) => handleProfileFieldChange('timezone', e.target.value)}
                placeholder="e.g., America/New_York"
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '4px', fontSize: '12px', fontWeight: '500' }}>Additional Information About Myself</label>
              <textarea
                value={userInfo.additional_info}
                onChange={(e) => handleProfileFieldChange('additional_info', e.target.value)}
                placeholder="Enter any additional information about yourself that you'd like the AI to know..."
                rows={4}
                style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid #ddd', fontSize: '14px', resize: 'vertical' }}
              />
            </div>
          </div>
          <div style={{ marginTop: '20px', display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => setCurrentView('chat')}
              className="send-button"
              style={{ padding: '8px 16px', background: '#666' }}
            >
              Cancel
            </button>
            <button
              onClick={handleSaveProfile}
              disabled={isSavingProfile}
              className="send-button"
              style={{ padding: '8px 16px' }}
            >
              {isSavingProfile ? 'Saving...' : 'Save Profile'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <div className="header">
        <h1>navAI</h1>
        <div className="header-actions">
          <button
            onClick={handleProfileClick}
            className="clear-button"
            title="Profile"
            style={{ marginRight: '8px' }}
          >
            Profile
          </button>
          {state.conversationHistory.length > 0 && (
            <button
              onClick={clearConversationHistory}
              className="clear-button"
              title="Clear conversation"
            >
              Clear
            </button>
          )}
        </div>
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
          Agentic Mode {state.agenticMode ? '(ON)' : '(OFF)'}
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
          onClick={handleToggleRecording}
          className={`send-button mic-button ${isRecording ? 'recording' : ''}`}
          title={isRecording ? 'Stop recording' : 'Start recording'}
        >
          {isRecording ? '🛑' : '🎤'}
        </button>
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
