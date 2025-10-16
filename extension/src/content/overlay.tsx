import React from 'react';
import ReactDOM from 'react-dom/client';

interface OverlayProps {
  message: string;
  visible: boolean;
  onClose: () => void;
}

const Overlay: React.FC<OverlayProps> = ({ message, visible, onClose }) => {
  if (!visible) return null;

  return (
    <div className="ai-assistant-overlay">
      <div className="ai-assistant-content">
        <div className="ai-assistant-header">
          <span className="ai-assistant-title">AI Assistant</span>
          <button className="ai-assistant-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="ai-assistant-message">
          {message}
        </div>
      </div>
    </div>
  );
};

export class OverlayManager {
  private overlayElement: HTMLDivElement | null = null;
  private root: ReactDOM.Root | null = null;

  constructor() {
    this.createOverlayElement();
  }

  private createOverlayElement() {
    // Create overlay container
    this.overlayElement = document.createElement('div');
    this.overlayElement.id = 'ai-assistant-overlay-container';
    this.overlayElement.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 2147483647;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    `;

    // Add styles
    const style = document.createElement('style');
    style.textContent = `
      .ai-assistant-overlay {
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 350px;
        max-width: calc(100vw - 40px);
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        pointer-events: auto;
        animation: slideIn 0.3s ease-out;
        color: white;
      }

      @keyframes slideIn {
        from {
          transform: translateY(100px);
          opacity: 0;
        }
        to {
          transform: translateY(0);
          opacity: 1;
        }
      }

      .ai-assistant-content {
        padding: 16px;
      }

      .ai-assistant-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }

      .ai-assistant-title {
        font-weight: 600;
        font-size: 14px;
      }

      .ai-assistant-close {
        background: none;
        border: none;
        color: white;
        font-size: 20px;
        cursor: pointer;
        padding: 0;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        transition: background 0.2s;
      }

      .ai-assistant-close:hover {
        background: rgba(255, 255, 255, 0.2);
      }

      .ai-assistant-message {
        font-size: 14px;
        line-height: 1.4;
        word-wrap: break-word;
      }
    `;

    document.head.appendChild(style);
    document.body.appendChild(this.overlayElement);

    // Create React root
    this.root = ReactDOM.createRoot(this.overlayElement);
  }

  show(message: string) {
    if (!this.overlayElement || !this.root) return;
    this.root.render(
      <Overlay
        message={message}
        visible={true}
        onClose={() => this.hide()}
      />
    );
  }

  hide() {
    if (!this.overlayElement || !this.root) return;
    this.root.render(
      <Overlay
        message=""
        visible={false}
        onClose={() => {}}
      />
    );
  }

  destroy() {
    if (this.overlayElement) {
      this.overlayElement.remove();
      this.overlayElement = null;
    }
    this.root = null;
  }
}
