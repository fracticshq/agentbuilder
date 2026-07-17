import React, { useEffect, useMemo, useState } from 'react';
import type { ProductData, ProductVariantData } from '../types';

interface ProductCardProps {
  product: ProductData;
  onViewDetails?: (product: ProductData) => void;
}

export const ProductCard: React.FC<ProductCardProps> = ({ product, onViewDetails }) => {
  const [imageError, setImageError] = useState(false);
  const [variantsExpanded, setVariantsExpanded] = useState(false);
  const variants = useMemo(() => product.variants || [], [product.variants]);
  const isVariantProduct = variants.length > 1 || Boolean(product.has_variants && variants.length > 0);
  const defaultVariant = useMemo(() => {
    if (!variants.length) return undefined;
    return variants.find((variant) => variant.is_default)
      || variants.find((variant) => variant.variant_id === product.default_variant_id || variant.id === product.default_variant_id)
      || variants[0];
  }, [variants, product.default_variant_id]);
  const [selectedVariantId, setSelectedVariantId] = useState<string | undefined>(
    getVariantId(defaultVariant)
  );
  const selectedVariant = useMemo(() => {
    if (!variants.length) return undefined;
    return variants.find((variant) => getVariantId(variant) === selectedVariantId) || defaultVariant || variants[0];
  }, [variants, selectedVariantId, defaultVariant]);
  const displayProduct = useMemo(() => mergeVariant(product, selectedVariant), [product, selectedVariant]);
  const visibleVariants = useMemo(
    () => getVisibleVariants(variants, selectedVariant, variantsExpanded),
    [variants, selectedVariant, variantsExpanded]
  );
  const hiddenVariantCount = Math.max(variants.length - visibleVariants.length, 0);
  const optionNames = useMemo(() => getOptionNames(variants), [variants]);

  useEffect(() => {
    setSelectedVariantId(getVariantId(defaultVariant));
    setImageError(false);
  }, [defaultVariant?.variant_id, defaultVariant?.id]);

  const formatPrice = (price?: number, currency?: string) => {
    if (price === undefined) return 'Price on request';

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

  const handleImageError = () => {
    setImageError(true);
  };

  const formatProductPrice = () => {
    if (
      variants.length > 1 &&
      !selectedVariant &&
      product.price_min !== undefined &&
      product.price_max !== undefined &&
      product.price_min !== product.price_max
    ) {
      return `${formatPrice(product.price_min, product.currency)} - ${formatPrice(product.price_max, product.currency)}`;
    }
    return formatPrice(displayProduct.price_minor ?? displayProduct.price, displayProduct.currency);
  };

  const handleViewDetails = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Track view details
    if (typeof window !== 'undefined' && (window as any).agentAnalytics) {
      (window as any).agentAnalytics.track('product_view_details', {
        sku: displayProduct.sku || 'unknown',
        name: displayProduct.name,
        variant_id: displayProduct.variant_id,
      });
    }
    
    if (onViewDetails) {
      onViewDetails(displayProduct);
    } else if (displayProduct.variant_url || displayProduct.product_url) {
      window.open(displayProduct.variant_url || displayProduct.product_url, '_blank', 'noopener,noreferrer');
    }
  };

  const selectedVariantLabel = selectedVariant ? getVariantPrimaryLabel(selectedVariant) : undefined;

  return (
    <div className={`product-card ${isVariantProduct ? 'variant-product-card' : ''} ${variantsExpanded ? 'expanded variants-expanded' : ''}`}>
      <div className="product-card-header">
        <div className="product-image-container">
          {(displayProduct.image_url || displayProduct.image) && !imageError ? (
            <img
              key={`${displayProduct.variant_id || displayProduct.sku || 'product'}:${displayProduct.image_url}`}
              src={displayProduct.image_url || displayProduct.image}
              alt={displayProduct.name}
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
        {displayProduct.category && (
          <span className="product-category">{displayProduct.category}</span>
        )}
        
        <div className="product-header-row">
          <h4 className="product-name">{displayProduct.name}</h4>
          {displayProduct.in_stock !== undefined && (
            <span className={`stock-badge ${displayProduct.in_stock ? 'in-stock' : 'out-of-stock'}`}>
              {displayProduct.in_stock ? '✓' : '✗'}
            </span>
          )}
        </div>
        
        <p className="product-sku">
          {displayProduct.sku ? `SKU: ${displayProduct.sku}` : 'SKU available on request'}
          {selectedVariantLabel ? ` (${selectedVariantLabel})` : ''}
        </p>
        {isVariantProduct && (
          <>
            <span className="product-price variant-product-price">{formatProductPrice()}</span>
            <VariantSelector
              product={product}
              visibleVariants={visibleVariants}
              selectedVariant={selectedVariant}
              optionNames={optionNames}
              hiddenVariantCount={hiddenVariantCount}
              expanded={variantsExpanded}
              onSelect={(variant) => {
                setSelectedVariantId(getVariantId(variant));
                setImageError(false);
              }}
              onExpand={() => setVariantsExpanded(true)}
            />
          </>
        )}
        
        <div className="product-price-row">
          {!isVariantProduct && <span className="product-price">{formatProductPrice()}</span>}
          {(displayProduct.variant_url || displayProduct.product_url || displayProduct.url) && (
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

function mergeVariant(product: ProductData, variant?: ProductVariantData): ProductData {
  if (!variant) return product;
  return {
    ...product,
    sku: variant.variant_sku || variant.sku || product.sku,
    price: variant.price_minor ?? variant.price ?? product.price_minor ?? product.price,
    price_minor: variant.price_minor ?? variant.price ?? product.price_minor ?? product.price,
    price_unit: 'minor',
    currency: variant.currency || product.currency,
    currency_source: variant.currency_source || product.currency_source,
    image_url: variant.image_url || variant.image || product.image_url || product.image,
    product_url: variant.product_url || product.product_url || product.url,
    // Some catalog sources only provide the parent product URL. Keep the
    // selected variant in the destination so changing an option cannot send
    // the shopper back to the default variant.
    variant_url: getVariantUrl(product, variant),
    in_stock: variant.in_stock ?? product.in_stock,
    variant_id: variant.variant_id || variant.id || product.variant_id,
    variant_title: variant.variant_title || variant.title || product.variant_title,
    variant_options: variant.variant_options || product.variant_options,
  };
}

function getVariantUrl(product: ProductData, variant: ProductVariantData): string | undefined {
  if (variant.variant_url) return variant.variant_url;

  const baseUrl = variant.product_url || product.product_url || product.url || product.variant_url;
  const rawVariantId = variant.variant_id || variant.id;
  if (!baseUrl || !rawVariantId) return baseUrl;

  const variantId = String(rawVariantId).split('/').pop() || String(rawVariantId);
  try {
    const url = new URL(baseUrl);
    url.searchParams.set('variant', variantId);
    return url.toString();
  } catch {
    const separator = baseUrl.includes('?') ? '&' : '?';
    return `${baseUrl}${separator}variant=${encodeURIComponent(variantId)}`;
  }
}

function VariantSelector({
  product,
  visibleVariants,
  selectedVariant,
  optionNames,
  hiddenVariantCount,
  expanded,
  onSelect,
  onExpand,
}: {
  product: ProductData;
  visibleVariants: ProductVariantData[];
  selectedVariant?: ProductVariantData;
  optionNames: string[];
  hiddenVariantCount: number;
  expanded: boolean;
  onSelect: (variant: ProductVariantData) => void;
  onExpand: () => void;
}) {
  const selectedId = getVariantId(selectedVariant);
  const sectionLabel = optionNames.length
    ? `Choose ${optionNames.join(' & ')}`
    : 'Choose variant';

  return (
    <div className="product-variant-selector" aria-label="Product variants">
      <div className="variant-section-label">{sectionLabel}</div>
      <div className="variant-tile-grid" data-expanded={expanded ? 'true' : 'false'}>
        {visibleVariants.map((variant) => {
          const id = getVariantId(variant);
          const primaryLabel = getVariantPrimaryLabel(variant);
          const secondaryLabel = getVariantSecondaryLabel(variant);
          const image = getVariantImage(variant, product);
          const selected = id === selectedId;

          return (
            <button
              key={id || primaryLabel}
              type="button"
              className={`variant-tile ${selected ? 'selected' : ''}`}
              title={[primaryLabel, secondaryLabel].filter(Boolean).join(' - ')}
              aria-pressed={selected}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(variant);
              }}
            >
              <span className="variant-tile-image-wrap">
                {image ? (
                  <img src={image} alt={primaryLabel} className="variant-tile-image" />
                ) : (
                  <span className="variant-tile-image-placeholder" aria-hidden="true" />
                )}
              </span>
              <span className="variant-tile-body">
                <span className="variant-tile-title">{primaryLabel}</span>
                {secondaryLabel && <span className="variant-tile-subtitle">{secondaryLabel}</span>}
                <span className="variant-tile-price">
                  {formatVariantPrice(variant.price, variant.currency || product.currency)}
                </span>
              </span>
              <span className="variant-tile-radio" aria-hidden="true" />
            </button>
          );
        })}
        {hiddenVariantCount > 0 && (
          <button
            type="button"
            className="variant-tile variant-more-tile"
            onClick={(event) => {
              event.stopPropagation();
              onExpand();
            }}
            aria-label={`View ${hiddenVariantCount} more variants`}
          >
            <span className="variant-more-count">+{hiddenVariantCount}</span>
            <span className="variant-more-label">more</span>
            <span className="variant-more-help">View all options</span>
          </button>
        )}
      </div>
    </div>
  );
}

function getVisibleVariants(
  variants: ProductVariantData[],
  selectedVariant?: ProductVariantData,
  expanded = false
): ProductVariantData[] {
  if (expanded || variants.length <= 4) return variants;
  const selectedId = getVariantId(selectedVariant);
  const visible = variants.slice(0, 4);
  if (!selectedId || visible.some((variant) => getVariantId(variant) === selectedId)) {
    return visible;
  }
  return [selectedVariant!, ...variants.filter((variant) => getVariantId(variant) !== selectedId).slice(0, 3)];
}

function getOptionNames(variants: ProductVariantData[]): string[] {
  const names: string[] = [];
  for (const variant of variants) {
    const options = variant.variant_options || {};
    for (const key of Object.keys(options)) {
      if (!names.includes(key)) names.push(key);
    }
  }
  return names;
}

function getVariantPrimaryLabel(variant: ProductVariantData): string {
  const options = variant.variant_options || {};
  const values = Object.values(options).filter(Boolean);
  if (values.length) return values[0];
  return variant.variant_title || variant.title || variant.variant_sku || variant.sku || 'Variant';
}

function getVariantSecondaryLabel(variant: ProductVariantData): string {
  const options = variant.variant_options || {};
  const values = Object.values(options).filter(Boolean);
  if (values.length > 1) return values.slice(1).join(' / ');
  return '';
}

function getVariantImage(variant: ProductVariantData, product: ProductData): string | undefined {
  return variant.image_url || variant.image || product.image_url || product.image;
}

function getVariantId(variant?: ProductVariantData): string {
  return variant?.variant_id || variant?.id || variant?.sku || variant?.variant_sku || variant?.title || '';
}

function formatVariantPrice(price?: number, currency?: string): string {
  if (price === undefined) return 'Price on request';
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
}
