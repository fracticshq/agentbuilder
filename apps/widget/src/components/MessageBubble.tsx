import React, { useMemo, useState, useEffect } from 'react';
import DOMPurify from 'dompurify';
import MarkdownIt from 'markdown-it';
import { ThumbsUp, ThumbsDown, Copy, RotateCcw } from 'lucide-react';
import type { Message, ProductData, KundaliChartData } from '../types';
import { ProductCard } from './ProductCard';
import { DealerCard } from './DealerCard';
import { KundaliChart } from './KundaliChart';

interface MessageBubbleProps {
  message: Message;
  userMsgBg?: string;
  userMsgColor?: string;
  assistantMsgBg?: string;
  assistantMsgColor?: string;
  onFeedback?: (id: string, feedback: 'up' | 'down' | null) => void;
  onRegenerate?: (id: string) => void;
  showSources?: boolean;
  showProductCards?: boolean;
  apiUrl?: string;
  agentId?: string | null;
}

// Initialize markdown-it instance
const md = new MarkdownIt({
  html: false,        // Disable HTML tags for security
  linkify: true,      // Auto-convert URLs to links
  typographer: true,  // Enable smart quotes and other typographic replacements
  breaks: true        // Convert \n to <br>
});

const defaultLinkOpenRenderer = md.renderer.rules.link_open || ((tokens, idx, options, _env, self) => {
  return self.renderToken(tokens, idx, options);
});

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank');
  tokens[idx].attrSet('rel', 'noopener noreferrer');
  return defaultLinkOpenRenderer(tokens, idx, options, env, self);
};

// Parse <product_info> tags and extract product SKUs
const parseProductInfo = (content: string): { cleanContent: string; productSkus: string[] } => {
  const productSkus: string[] = [];
  const productInfoRegex = /<product_info>([\s\S]*?)<\/product_info>/g;
  
  let match;
  while ((match = productInfoRegex.exec(content)) !== null) {
    const productBlock = match[1];
    // Extract product_sku value
    const skuMatch = productBlock.match(/product_sku:\s*\[?([^\]\n]+)\]?/);
    if (skuMatch && skuMatch[1]) {
      productSkus.push(
        ...skuMatch[1]
          .split(',')
          .map((sku) => sku.trim().replace(/^['"\s]+|['"\s]+$/g, ''))
          .filter(Boolean),
      );
    }
  }
  
  // Remove <product_info> tags from content
  const cleanContent = content.replace(productInfoRegex, '').trim();
  
  return { cleanContent, productSkus };
};

const getProductKey = (product: Partial<ProductData>): string =>
  product.product_group_id || (product as { product_id?: string }).product_id || product.product_url || product.sku || product.id || product.name || JSON.stringify(product);

const getUrlHost = (url?: string): string => {
  if (!url) {
    return '';
  }

  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
};

const getSafeCheckoutUrl = (message: Message): string | undefined => {
  const candidate = message.commerce?.cart?.checkout_url || (message.metadata?.cart as { checkout_url?: string } | undefined)?.checkout_url;
  if (!candidate) return undefined;
  try {
    const parsed = new URL(candidate);
    return parsed.protocol === 'https:' ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
};

const formatProductPrice = (price?: number, currency?: string): string => {
  if (price === undefined) return '';

  const displayPrice = price / 100;
  if (!currency) {
    return displayPrice.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(displayPrice);
  } catch {
    return `${currency} ${displayPrice.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
};

// Fetch product details from API
const fetchProductDetails = async (skus: string[], agentId: string, apiUrl?: string): Promise<ProductData[]> => {
  try {
    console.log('[MessageBubble] Fetching products for SKUs:', skus, 'agentId:', agentId);
    const sessionKey = `agent_widget_session_v1_${encodeURIComponent(window.location.origin)}_${agentId}`;
    let sessionToken: string | undefined;
    try {
      sessionToken = JSON.parse(sessionStorage.getItem(sessionKey) || '{}').sessionToken;
    } catch {
      sessionToken = undefined;
    }
    const baseUrl = (apiUrl || window.__APP_CONFIG__?.API_BASE_URL || window.location.origin).replace(/\/$/, '');
    const response = await fetch(`${baseUrl}/api/v1/public/catalog/products`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(sessionToken ? { 'X-Widget-Session': sessionToken } : {}),
      },
      body: JSON.stringify({
        skus,
        agent_id: agentId
      })
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('[MessageBubble] Failed to fetch products:', response.status, response.statusText, errorText);
      throw new Error(`Product hydration failed: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('[MessageBubble] Received products:', data);
    return data.products || [];
  } catch (error) {
    console.error('[MessageBubble] Error fetching products:', error);
    return [];
  }
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message,
  userMsgBg = '#2563eb',
  userMsgColor = '#ffffff',
  assistantMsgBg = '#f3f4f6',
  assistantMsgColor = '#111827',
  onFeedback,
  onRegenerate,
  showSources = false,
  showProductCards = true,
  apiUrl,
  agentId,
}) => {
  const isUser = message.role === 'user';
  const [extractedProducts, setExtractedProducts] = useState<ProductData[]>([]);
  const [hydrationState, setHydrationState] = useState<'idle' | 'loading' | 'ready' | 'empty' | 'error'>('idle');
  const [isHovered, setIsHovered] = useState(false);
  
  // Parse product info tags and fetch product details
  useEffect(() => {
    if (isUser || !showProductCards || !message.content) {
      setExtractedProducts([]);
      setHydrationState('idle');
      return;
    }

    const { productSkus } = parseProductInfo(message.content);

    if (productSkus.length === 0) {
      setExtractedProducts([]);
      setHydrationState('idle');
      return;
    }

    const resolvedAgentId = agentId || new URLSearchParams(window.location.search).get('agent_id') || '';
    if (!resolvedAgentId) {
      setHydrationState('error');
      return;
    }

    setHydrationState('loading');
    fetchProductDetails(productSkus, resolvedAgentId, apiUrl)
      .then(products => {
        console.log('[MessageBubble] Fetched products:', products);
        setExtractedProducts(products);
        setHydrationState(products.length ? 'ready' : 'empty');
      })
      .catch(() => {
        setExtractedProducts([]);
        setHydrationState('error');
      });
  }, [message.content, isUser, showProductCards, agentId, apiUrl]);
  
  // Render markdown content with product tags removed
  const renderedContent = useMemo(() => {
    if (isUser) {
      return message.content; // User messages stay as plain text
    }
    const { cleanContent } = parseProductInfo(message.content);
    return md.render(cleanContent);
  }, [message.content, isUser]);
  
  // Structured kundali chart calculated by the backend (Lal Kitab agents).
  const kundaliChart = useMemo(() => {
    if (isUser) return null;
    const data = message.metadata?.kundali_chart as KundaliChartData | undefined;
    return data && Array.isArray(data.houses) && data.houses.length ? data : null;
  }, [message.metadata, isUser]);

  // Combine products from message metadata and extracted from tags
  const allProducts = useMemo(() => {
    const products = [...(message.products || []), ...extractedProducts];
    const merged = new Map<string, ProductData>();
    products.forEach((product) => {
      const key = getProductKey(product);
      const existing = merged.get(key);
      if (!existing) {
        merged.set(key, product);
        return;
      }
      const variants = [...(existing.variants || []), ...(product.variants || [])];
      const seenVariants = new Set<string>();
      merged.set(key, {
        ...existing,
        ...product,
        variants: variants.filter((variant) => {
          const variantKey = variant.variant_id || variant.id || variant.sku || variant.variant_sku || variant.title || JSON.stringify(variant);
          if (seenVariants.has(variantKey)) return false;
          seenVariants.add(variantKey);
          return true;
        }),
      });
    });
    return Array.from(merged.values());
  }, [message.products, extractedProducts]);
  const checkoutUrl = getSafeCheckoutUrl(message);
  
  // Helper to check if citation is about a product
  const getProductForCitation = (citation: { doc_id: string; title?: string; url?: string; snippet?: string }) => {
    // Check if citation title or snippet contains a product SKU
    for (const product of allProducts) {
      const sku = product.sku || '';
      if ((sku && citation.title?.includes(sku)) || 
          (sku && citation.snippet?.includes(sku)) ||
          (sku && citation.doc_id?.includes(sku))) {
        return product;
      }
    }
    return null;
  };
  
  console.log('[MessageBubble] Rendering message:', {
    id: message.id,
    role: message.role,
    contentLength: message.content.length,
    content: message.content.substring(0, 50) + (message.content.length > 50 ? '...' : ''),
    hasProducts: allProducts.length > 0,
    productsCount: allProducts.length,
    hasDealers: !!message.dealers && message.dealers.length > 0,
    dealersCount: message.dealers?.length || 0,
  });
  
  const handleFeedback = (feedback: 'up' | 'down') => {
    const next = message.feedback === feedback ? null : feedback;
    onFeedback?.(message.id, next);
  };

  return (
    <div
      className={`message-bubble ${isUser ? 'user' : 'assistant'} message-bubble-wrapper`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={`message-content ${isUser ? 'user-message' : 'assistant-message'}`}
        style={isUser
          ? { background: userMsgBg, color: userMsgColor }
          : { background: assistantMsgBg, color: assistantMsgColor }
        }
      >
        {/* Lal Kitab kundali — visual chart artifact, always ahead of the reading */}
        {!isUser && kundaliChart && <KundaliChart data={kundaliChart} />}

        {isUser ? (
          <p className="message-text">{message.content}</p>
        ) : (
          <>
            {/* markdown-it rejects raw HTML; DOMPurify protects this final browser sink. */}
            <div
              className="message-text markdown-content"
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(renderedContent, {
                  USE_PROFILES: { html: true },
                }),
              }}
            />
          </>
        )}
        
        {/* Phase 5: Product Cards - from metadata OR extracted from <product_info> tags */}
        {!isUser && showProductCards && allProducts.length > 0 && (
          <div className="product-cards-container">
            <div className="cards-label">
              {allProducts.length === 1 ? 'Product:' : 'Products:'}
            </div>
            <div className="cards-grid">
              {allProducts.map((product) => (
                <ProductCard key={getProductKey(product)} product={product} />
              ))}
            </div>
          </div>
        )}

        {!isUser && checkoutUrl && (
          <div className="checkout-action" role="status">
            <span className="checkout-action-label">Your cart is ready.</span>
            <a
              href={checkoutUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="checkout-action-btn"
            >
              Continue to Shopify checkout →
            </a>
          </div>
        )}

        {!isUser && showProductCards && hydrationState !== 'idle' && hydrationState !== 'ready' && allProducts.length === 0 && (
          <div className="product-hydration-status" role="status">
            {hydrationState === 'loading' ? 'Loading product details…' : 'Product details are unavailable right now.'}
          </div>
        )}
        
        {/* Phase 5: Dealer Cards */}
        {!isUser && message.dealers && message.dealers.length > 0 && (
          <div className="dealer-cards-container">
            <div className="cards-label">
              {message.dealers.length === 1 ? 'Dealer:' : 'Dealers:'}
            </div>
            <div className="cards-grid">
              {message.dealers.map((dealer) => (
                <DealerCard key={dealer.dealer_id} dealer={dealer} />
              ))}
            </div>
          </div>
        )}
        
        {showSources && message.citations && message.citations.length > 0 && (
          <div className="citations">
            <div className="citations-label">Sources</div>
            <div className="citations-grid">
              {message.citations.map((citation, index) => {
                const relatedProduct = getProductForCitation(citation);
                
                return (
                  <div key={index} className="citation">
                    <div className="citation-number">{index + 1}</div>
                    <div className="citation-content">
                      <a 
                        href={relatedProduct?.product_url || citation.url || '#'} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="citation-link"
                        title={relatedProduct ? `${relatedProduct.name} (${relatedProduct.sku})` : citation.title}
                      >
                        {relatedProduct 
                          ? `${relatedProduct.name} • ${relatedProduct.sku}`
                          : citation.title || 'Source'}
                      </a>
                      {(relatedProduct?.product_url || citation.url) && (
                        <div className="citation-url">
                          {relatedProduct?.product_url
                            ? getUrlHost(relatedProduct.product_url)
                            : getUrlHost(citation.url)}
                        </div>
                      )}
                      {citation.snippet && !relatedProduct && (
                        <p className="citation-snippet">{citation.snippet}</p>
                      )}
                      {relatedProduct && relatedProduct.category && (
                        <p className="citation-snippet">
                          Category: {relatedProduct.category}
                          {(relatedProduct.price_minor ?? relatedProduct.price) && ` • ${formatProductPrice(relatedProduct.price_minor ?? relatedProduct.price, relatedProduct.currency)}`}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <div className="message-timestamp">
          {new Date(message.timestamp).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
          })}
        </div>
      </div>

      {!isUser && (
        <div className="message-actions" style={{ opacity: isHovered ? 1 : 0 }}>
          <button
            className="message-action-btn"
            onClick={() => navigator.clipboard.writeText(message.content)}
            title="Copy"
            aria-label="Copy message"
          >
            <Copy size={14} />
          </button>
          <button
            className={`message-action-btn${message.feedback === 'up' ? ' active' : ''}`}
            onClick={() => handleFeedback('up')}
            title="Helpful"
            aria-label="Mark helpful"
          >
            <ThumbsUp size={14} />
          </button>
          <button
            className={`message-action-btn${message.feedback === 'down' ? ' active' : ''}`}
            onClick={() => handleFeedback('down')}
            title="Not helpful"
            aria-label="Mark not helpful"
          >
            <ThumbsDown size={14} />
          </button>
          <button
            className="message-action-btn"
            onClick={() => onRegenerate?.(message.id)}
            title="Regenerate"
            aria-label="Regenerate response"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      )}
    </div>
  );
};
