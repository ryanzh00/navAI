// Configuration for the extension
// Adjust BACKEND_URL for different environments (local dev, staging, production)

export const BACKEND_URL = 'http://localhost:8000';

export const API_ENDPOINTS = {
  chat: `${BACKEND_URL}/chat`,
  debug: `${BACKEND_URL}/debug/mcp-snapshot`,
  openBrowser: `${BACKEND_URL}/open`,
  status: `${BACKEND_URL}/status`,
  getUserInfo: `${BACKEND_URL}/user/info`,
  updateUserInfo: `${BACKEND_URL}/user/info`,
};

// Helper to generate a unique ID (UUID v4-like)
export function generateId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}
