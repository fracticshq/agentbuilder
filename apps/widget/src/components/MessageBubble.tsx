import React, { useMemo, useState, useEffect } from 'react';
import MarkdownIt from 'markdown-it';
import type { Message } from '../types';
import { ProductCard } from './ProductCard';
import { DealerCard } from './DealerCard';

interface MessageBubbleProps {
  message: Message;
  userMsgBg?: string;
  userMsgColor?: string;
  assistantMsgBg?: string;
  assistantMsgColor?: string;
}

interface Product {
  sku: string;
  name: string;
  price: number;
  currency: string;
  category: string;
  in_stock: boolean;
  features?: string[];
  image_url?: string;
  product_url?: string;
}

// Initialize markdown-it instance
const md = new MarkdownIt({
  html: false,        // Disable HTML tags for security
  linkify: true,      // Auto-convert URLs to links
  typographer: true,  // Enable smart quotes and other typographic replacements
  breaks: true        // Convert \n to <br>
});

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
      productSkus.push(skuMatch[1].trim());
    }
  }
  
  // Remove <product_info> tags from content
  const cleanContent = content.replace(productInfoRegex, '').trim();
  
  return { cleanContent, productSkus };
};

// Fetch product details from API
const fetchProductDetails = async (skus: string[], agentId: string): Promise<Product[]> => {
  try {
    console.log('[MessageBubble] Fetching products for SKUs:', skus, 'agentId:', agentId);
    const response = await fetch(`http://localhost:8000/api/v1/knowledge/products/by-skus`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        skus,
        agent_id: agentId
      })
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error('[MessageBubble] Failed to fetch products:', response.status, response.statusText, errorText);
      return [];
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
}) => {
  const isUser = message.role === 'user';
  const [extractedProducts, setExtractedProducts] = useState<Product[]>([]);
  
  // Parse product info tags and fetch product details
  useEffect(() => {
    if (!isUser && message.content) {
      const { productSkus } = parseProductInfo(message.content);
      
      if (productSkus.length > 0) {
        // Get agent ID from URL or localStorage
        const urlParams = new URLSearchParams(window.location.search);
        const agentId = urlParams.get('agent_id') || localStorage.getItem('agent_widget_agent_id') || '';
        
        fetchProductDetails(productSkus, agentId)
          .then(products => {
            console.log('[MessageBubble] Fetched products:', products);
            setExtractedProducts(products);
          });
      }
    }
  }, [message.content, isUser]);
  
  // Render markdown content with product tags removed
  const renderedContent = useMemo(() => {
    if (isUser) {
      return message.content; // User messages stay as plain text
    }
    const { cleanContent } = parseProductInfo(message.content);
    return md.render(cleanContent);
  }, [message.content, isUser]);
  
  // Combine products from message metadata and extracted from tags
  const allProducts = useMemo(() => {
    const products = [...(message.products || []), ...extractedProducts];
    // Deduplicate by SKU
    const seen = new Set();
    return products.filter(p => {
      if (seen.has(p.sku)) return false;
      seen.add(p.sku);
      return true;
    });
  }, [message.products, extractedProducts]);
  
  // Helper to check if citation is about a product
  const getProductForCitation = (citation: { doc_id: string; title?: string; url?: string; snippet?: string }) => {
    // Check if citation title or snippet contains a product SKU
    for (const product of allProducts) {
      if (citation.title?.includes(product.sku) || 
          citation.snippet?.includes(product.sku) ||
          citation.doc_id?.includes(product.sku)) {
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
  
  return (
    <div className={`message-bubble ${isUser ? 'user' : 'assistant'}`}>
      <div
        className={`message-content ${isUser ? 'user-message' : 'assistant-message'}`}
        style={isUser
          ? { background: userMsgBg, color: userMsgColor }
          : { background: assistantMsgBg, color: assistantMsgColor }
        }
      >
        {isUser ? (
          <p className="message-text">{message.content}</p>
        ) : (
          <div 
            className="message-text markdown-content" 
            dangerouslySetInnerHTML={{ __html: renderedContent }}
          />
        )}
        
        {/* Phase 5: Product Cards - from metadata OR extracted from <product_info> tags */}
        {!isUser && allProducts.length > 0 && (
          <div className="product-cards-container">
            <div className="cards-label">
              {allProducts.length === 1 ? 'Product:' : 'Products:'}
            </div>
            <div className="cards-grid">
              {allProducts.map((product) => (
                <ProductCard key={product.sku} product={product} />
              ))}
            </div>
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
        
        {message.citations && message.citations.length > 0 && (
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
                            ? new URL(relatedProduct.product_url).hostname
                            : citation.url ? new URL(citation.url).hostname : ''}
                        </div>
                      )}
                      {citation.snippet && !relatedProduct && (
                        <p className="citation-snippet">{citation.snippet}</p>
                      )}
                      {relatedProduct && relatedProduct.category && (
                        <p className="citation-snippet">
                          Category: {relatedProduct.category}
                          {relatedProduct.price && ` • ${relatedProduct.currency === 'INR' ? '₹' : '$'}${relatedProduct.price.toLocaleString()}`}
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
    </div>
  );
};
