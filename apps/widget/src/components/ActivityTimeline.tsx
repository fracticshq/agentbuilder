import React from 'react';
import type { ActivityState, ActivityStep, PlaceCandidate } from '../types';

interface ActivityTimelineProps {
  state: ActivityState;
  /** Text to show when no real events have arrived yet (graceful fallback). */
  fallbackText?: string;
  fallbackVisible?: boolean;
  accentColor?: string;
  textColor?: string;
  bgColor?: string;
  /** Invoked when a user picks a candidate in a disambiguation prompt. */
  onSelectPlace?: (label: string) => void;
}

const StepIcon: React.FC<{ status: ActivityStep['status']; color: string }> = ({ status, color }) => {
  if (status === 'done') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <polyline points="20 6 9 17 4 12" />
      </svg>
    );
  }
  if (status === 'error') {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    );
  }
  // running
  return <span className="activity-spinner" style={{ borderTopColor: color, borderRightColor: color }} aria-hidden />;
};

export const ActivityTimeline: React.FC<ActivityTimelineProps> = ({
  state,
  fallbackText,
  fallbackVisible = true,
  accentColor = 'rgba(255,255,255,0.9)',
  textColor = 'rgba(255,255,255,0.85)',
  bgColor = 'rgba(255,255,255,0.06)',
  onSelectPlace,
}) => {
  const { steps, disambiguation } = state;
  const hasSteps = steps.length > 0;

  // No real events yet — show the lightweight dots + fallback text.
  if (!hasSteps && !disambiguation) {
    return (
      <div className="typing-indicator">
        <div className="typing-dots" style={{ background: bgColor, display: 'flex', alignItems: 'center', gap: 8, paddingRight: 12 }}>
          <span className="dot" style={{ background: textColor }} />
          <span className="dot" style={{ background: textColor }} />
          <span className="dot" style={{ background: textColor }} />
          {fallbackText && (
            <span
              className="thinking-status-text"
              style={{ color: textColor, opacity: fallbackVisible ? 0.7 : 0, transition: 'opacity 0.3s ease' }}
            >
              {fallbackText}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="activity-timeline" style={{ background: bgColor }}>
      {steps.map((step) => {
        const dim = step.status === 'done';
        const color = step.status === 'error' ? '#e5683f' : accentColor;
        return (
          <div key={step.id} className="activity-step">
            <span className="activity-step-icon">
              <StepIcon status={step.status} color={color} />
            </span>
            <span
              className="activity-step-label"
              style={{ color: textColor, opacity: dim ? 0.55 : 0.95 }}
            >
              {step.label}
            </span>
            {step.detail && (
              <span className="activity-step-detail" style={{ color: textColor }}>{step.detail}</span>
            )}
          </div>
        );
      })}

      {disambiguation && (
        <div className="activity-disambiguation">
          {disambiguation.candidates.map((c: PlaceCandidate, i) => (
            <button
              key={c.placeId || `${c.label}-${i}`}
              type="button"
              className="activity-place-chip"
              style={{ borderColor: accentColor, color: textColor }}
              onClick={() => onSelectPlace?.(c.label)}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
