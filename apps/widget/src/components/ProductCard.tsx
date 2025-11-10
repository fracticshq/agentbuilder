import React, { useState } from 'react';
import type { ProductData } from '../types';

interface ProductCardProps {
  product: ProductData;
  onViewDetails?: (product: ProductData) => void;
}

export const ProductCard: React.FC<ProductCardProps> = ({ product, onViewDetails }) => {
  const [imageError, setImageError] = useState(false);

  const formatPrice = (price?: number, currency?: string) => {
    if (price === undefined) return 'Price on request';
    
    const currencySymbol = currency === 'INR' ? '₹' : 
                          currency === 'USD' ? '$' : 
                          currency === 'EUR' ? '€' : 
                          currency || '₹';
    
    return `${currencySymbol}${price.toLocaleString()}`;
  };

  const handleImageError = () => {
    setImageError(true);
  };

  const handleViewDetails = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Track view details
    if (typeof window !== 'undefined' && (window as any).agentAnalytics) {
      (window as any).agentAnalytics.track('product_view_details', {
        sku: product.sku,
        name: product.name
      });
    }
    
    if (onViewDetails) {
      onViewDetails(product);
    } else if (product.product_url) {
      window.open(product.product_url, '_blank', 'noopener,noreferrer');
    }
  };

  return (
    <div className="product-card">
      <div className="product-card-header">
        <div className="product-image-container">
          {product.image_url && !imageError ? (
            <img
              src={product.image_url}
              alt={product.name}
              className="product-image"
              onError={handleImageError}
            />
          ) : (
            <div className="product-image-placeholder">
              <svg 
                className="product-icon" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24"
              >
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth={2} 
                  d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" 
                />
              </svg>
            </div>
          )}
        </div>
      </div>
      
      <div className="product-info">
        {product.category && (
          <span className="product-category">{product.category}</span>
        )}
        
        <div className="product-header-row">
          <h4 className="product-name">{product.name}</h4>
          {product.in_stock !== undefined && (
            <span className={`stock-badge ${product.in_stock ? 'in-stock' : 'out-of-stock'}`}>
              {product.in_stock ? '✓' : '✗'}
            </span>
          )}
        </div>
        
        <p className="product-sku">SKU: {product.sku}</p>
        
        <div className="product-price-row">
          <span className="product-price">{formatPrice(product.price, product.currency)}</span>
          {product.product_url && (
            <button 
              className="view-details-btn"
              onClick={handleViewDetails}
              aria-label="Learn more about this product"
            >
              Learn More →
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
