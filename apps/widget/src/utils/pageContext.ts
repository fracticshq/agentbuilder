import type { PageContext } from '../types';

export function extractPageContext(): PageContext {
  const pageUrl = new URL(window.location.href);
  const context: PageContext = {
    url: window.location.href,
    title: document.title,
    path: pageUrl.pathname,
  };

  // Extract meta description
  const metaDescription = document.querySelector('meta[name="description"]');
  if (metaDescription) {
    context.metadata = {
      description: metaDescription.getAttribute('content'),
    };
  }

  const sku = findMetaContent([
    'meta[property="product:retailer_item_id"]',
    'meta[name="sku"]',
    'meta[itemprop="sku"]',
  ]) || document.querySelector('[data-sku]')?.getAttribute('data-sku') || undefined;
  if (sku) {
    context.sku = sku;
  }

  const category = findMetaContent([
    'meta[property="product:category"]',
    'meta[name="category"]',
    'meta[itemprop="category"]',
  ]) || document.querySelector('[data-category]')?.getAttribute('data-category') || undefined;
  if (category) {
    context.category = category;
  }

  // Extract main content (simplified version)
  const mainContent = extractMainContent();
  if (mainContent) {
    context.content = mainContent;
  }

  return context;
}

function findMetaContent(selectors: string[]): string | undefined {
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const content = element?.getAttribute('content');
    if (content?.trim()) {
      return content.trim();
    }
  }
  return undefined;
}

function extractMainContent(): string {
  // Try to find main content areas
  const selectors = [
    'main',
    '[role="main"]',
    'article',
    '.content',
    '.main-content',
    '.post-content',
    '#content',
    '#main',
  ];

  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (element) {
      return cleanText(element.textContent || '');
    }
  }

  // Fallback to body content, but exclude common navigation/footer elements
  const body = document.body.cloneNode(true) as HTMLElement;
  
  // Remove unwanted elements
  const unwantedSelectors = [
    'nav', 'header', 'footer', 'aside',
    '.nav', '.header', '.footer', '.sidebar',
    '.menu', '.advertisement', '.ads',
    'script', 'style', 'noscript'
  ];
  
  unwantedSelectors.forEach(selector => {
    const elements = body.querySelectorAll(selector);
    elements.forEach(el => el.remove());
  });

  return cleanText(body.textContent || '').slice(0, 2000); // Limit to 2000 chars
}

function cleanText(text: string): string {
  return text
    .replace(/\s+/g, ' ') // Normalize whitespace
    .replace(/\n\s*\n/g, '\n') // Remove excessive line breaks
    .trim();
}

export function generateUserId(): string {
  // Generate a persistent user ID (stored in localStorage)
  const storageKey = 'agent-widget-user-id';
  let userId = localStorage.getItem(storageKey);
  
  if (!userId) {
    userId = `user-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    localStorage.setItem(storageKey, userId);
  }
  
  return userId;
}

export function formatTimestamp(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}
