// Content script utilities for capturing page content

import { PageData } from '../types';

/**
 * Extract text content from the page
 */
export function extractPageText(): string {
  // Remove script and style elements
  const scripts = document.querySelectorAll('script, style, nav, header, footer');
  scripts.forEach(el => el.remove());
  
  // Get all text content
  const textContent = document.body.innerText || document.body.textContent || '';
  
  // Clean up whitespace
  return textContent
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Extract headings from the page
 */
export function extractHeadings(): string[] {
  const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
  return Array.from(headings).map(heading => heading.textContent?.trim() || '');
}

/**
 * Capture comprehensive page data
 */
export function capturePageData(): PageData {
  return {
    url: window.location.href,
    title: document.title,
    text: extractPageText(),
    headings: extractHeadings()
  };
}

/**
 * Get page summary for context
 */
export function getPageSummary(): string {
  const title = document.title;
  const headings = extractHeadings().slice(0, 5); // First 5 headings
  const text = extractPageText().substring(0, 500); // First 500 chars
  
  return `Page: ${title}\nHeadings: ${headings.join(', ')}\nContent: ${text}...`;
}
