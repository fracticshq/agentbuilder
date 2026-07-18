import React, { useState } from 'react';
import type { DealerData } from '../types';

interface DealerCardProps {
  dealer: DealerData;
  onViewMap?: (dealer: DealerData) => void;
}

export const DealerCard: React.FC<DealerCardProps> = ({ dealer, onViewMap }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleCardClick = () => {
    setIsExpanded(!isExpanded);
    
    // Track card interaction
    if (typeof window !== 'undefined' && window.agentAnalytics) {
      window.agentAnalytics.track('dealer_card_click', {
        dealer_id: dealer.dealer_id,
        name: dealer.name,
        city: dealer.city,
        action: isExpanded ? 'collapse' : 'expand'
      });
    }
  };

  const handleViewMap = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Track map view
    if (typeof window !== 'undefined' && window.agentAnalytics) {
      window.agentAnalytics.track('dealer_view_map', {
        dealer_id: dealer.dealer_id,
        name: dealer.name,
        city: dealer.city
      });
    }
    
    if (onViewMap) {
      onViewMap(dealer);
    } else if (dealer.map_url) {
      window.open(dealer.map_url, '_blank', 'noopener,noreferrer');
    } else if (dealer.address) {
      // Generate Google Maps URL from address
      const mapsUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(dealer.address)}`;
      window.open(mapsUrl, '_blank', 'noopener,noreferrer');
    }
  };

  const handlePhoneClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Track phone click
    if (typeof window !== 'undefined' && window.agentAnalytics) {
      window.agentAnalytics.track('dealer_phone_click', {
        dealer_id: dealer.dealer_id,
        name: dealer.name
      });
    }
  };

  const handleEmailClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    
    // Track email click
    if (typeof window !== 'undefined' && window.agentAnalytics) {
      window.agentAnalytics.track('dealer_email_click', {
        dealer_id: dealer.dealer_id,
        name: dealer.name
      });
    }
  };

  return (
    <div className={`dealer-card ${isExpanded ? 'expanded' : ''}`} onClick={handleCardClick}>
      <div className="dealer-card-header">
        <div className="dealer-icon-container">
          <svg className="dealer-icon" fill="currentColor" viewBox="0 0 20 20">
            <path 
              fillRule="evenodd" 
              d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" 
              clipRule="evenodd" 
            />
          </svg>
        </div>
        
        <div className="dealer-info">
          <h4 className="dealer-name">{dealer.name}</h4>
          
          <div className="dealer-location">
            <svg className="location-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                strokeWidth={2} 
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" 
              />
              <path 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                strokeWidth={2} 
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" 
              />
            </svg>
            <span className="location-text">
              {dealer.city}{dealer.state ? `, ${dealer.state}` : ''}
            </span>
          </div>

          {!isExpanded && (dealer.phone || dealer.email) && (
            <div className="dealer-quick-contact">
              {dealer.phone && (
                <a 
                  href={`tel:${dealer.phone}`} 
                  className="contact-link phone"
                  onClick={handlePhoneClick}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Call dealer"
                >
                  <svg className="contact-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path 
                      strokeLinecap="round" 
                      strokeLinejoin="round" 
                      strokeWidth={2} 
                      d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" 
                    />
                  </svg>
                </a>
              )}
              {dealer.email && (
                <a 
                  href={`mailto:${dealer.email}`} 
                  className="contact-link email"
                  onClick={handleEmailClick}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Email dealer"
                >
                  <svg className="contact-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path 
                      strokeLinecap="round" 
                      strokeLinejoin="round" 
                      strokeWidth={2} 
                      d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" 
                    />
                  </svg>
                </a>
              )}
            </div>
          )}
        </div>
      </div>

      {isExpanded && (
        <div className="dealer-card-details">
          {dealer.address && (
            <div className="dealer-address">
              <div className="detail-label">
                <svg className="detail-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth={2} 
                    d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" 
                  />
                </svg>
                Address
              </div>
              <p className="detail-value">{dealer.address}</p>
            </div>
          )}

          {dealer.phone && (
            <div className="dealer-phone">
              <div className="detail-label">
                <svg className="detail-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth={2} 
                    d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" 
                  />
                </svg>
                Phone
              </div>
              <a 
                href={`tel:${dealer.phone}`} 
                className="detail-value contact-value"
                onClick={handlePhoneClick}
                target="_blank"
                rel="noopener noreferrer"
              >
                {dealer.phone}
              </a>
            </div>
          )}

          {dealer.email && (
            <div className="dealer-email">
              <div className="detail-label">
                <svg className="detail-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth={2} 
                    d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" 
                  />
                </svg>
                Email
              </div>
              <a 
                href={`mailto:${dealer.email}`} 
                className="detail-value contact-value"
                onClick={handleEmailClick}
                target="_blank"
                rel="noopener noreferrer"
              >
                {dealer.email}
              </a>
            </div>
          )}

          {dealer.hours && (
            <div className="dealer-hours">
              <div className="detail-label">
                <svg className="detail-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth={2} 
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" 
                  />
                </svg>
                Hours
              </div>
              <p className="detail-value">{dealer.hours}</p>
            </div>
          )}

          <div className="dealer-actions">
            <button 
              className="dealer-action-btn primary"
              onClick={handleViewMap}
            >
              <svg className="btn-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth={2} 
                  d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" 
                />
              </svg>
              View on Map
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
