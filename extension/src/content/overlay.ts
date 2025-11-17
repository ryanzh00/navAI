/**
 * Overlay manager using vanilla JavaScript (no React)
 * Displays assistant messages at the bottom-right of the page
 */

export class OverlayManager {
  private overlayElement: HTMLDivElement | null = null;
  private messageElement: HTMLDivElement | null = null;

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
        display: flex;
        flex-direction: column;
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
        gap: 12px;
      }

      .ai-assistant-title {
        font-weight: 600;
        font-size: 14px;
        flex: 1;
      }

      .ai-assistant-close {
        background: none;
        border: none;
        color: white;
        font-size: 24px;
        cursor: pointer;
        padding: 0;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.8;
        transition: opacity 0.2s;
      }

      .ai-assistant-close:hover {
        opacity: 1;
      }

      .ai-assistant-message {
        font-size: 14px;
        line-height: 1.5;
        word-wrap: break-word;
        white-space: pre-wrap;
      }
    `;

    document.head.appendChild(style);
    document.body.appendChild(this.overlayElement);
  }

  show(message: string) {
    if (!this.overlayElement) return;

    // Clear previous content
    this.overlayElement.innerHTML = '';

    // Create overlay wrapper
    const overlay = document.createElement('div');
    overlay.className = 'ai-assistant-overlay';

    // Create content container
    const content = document.createElement('div');
    content.className = 'ai-assistant-content';

    // Create header with title and close button
    const header = document.createElement('div');
    header.className = 'ai-assistant-header';

    const title = document.createElement('span');
    title.className = 'ai-assistant-title';
    title.textContent = 'AI Assistant';

    const closeBtn = document.createElement('button');
    closeBtn.className = 'ai-assistant-close';
    closeBtn.textContent = '×';
    closeBtn.onclick = () => this.hide();

    header.appendChild(title);
    header.appendChild(closeBtn);

    // Create message element
    this.messageElement = document.createElement('div');
    this.messageElement.className = 'ai-assistant-message';
    this.messageElement.textContent = message;

    // Assemble overlay
    content.appendChild(header);
    content.appendChild(this.messageElement);
    overlay.appendChild(content);
    this.overlayElement.appendChild(overlay);

    // Show overlay
    this.overlayElement.style.pointerEvents = 'auto';
  }

  hide() {
    if (this.overlayElement) {
      this.overlayElement.innerHTML = '';
      this.overlayElement.style.pointerEvents = 'none';
    }
  }

  update(message: string) {
    if (this.messageElement) {
      this.messageElement.textContent = message;
    }
  }
}
