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
  /** Render as a collapsed, persistent trace attached to a finished answer. */
  persisted?: boolean;
}

function activitySummary(steps: ActivityStep[]): string {
  const total = steps.length;
  const errors = steps.filter((s) => s.status === 'error').length;
  const noun = total === 1 ? 'step' : 'steps';
  if (errors > 0) return `Ran ${total} ${noun} · ${errors} failed`;
  return `Ran ${total} ${noun}`;
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
  persisted = false,
}) => {
  const { steps, disambiguation } = state;
  const hasSteps = steps.length > 0;
  const hasError = steps.some((s) => s.status === 'error');
  const [expanded, setExpanded] = React.useState(false);

  // Persisted trace attached to a completed answer: a collapsible summary that
  // expands to the full step list, so users can see what ran and what didn't.
  if (persisted) {
    if (!hasSteps) return null;
    return (
      <div className="activity-timeline activity-persisted" style={{ background: bgColor }}>
        <button
          type="button"
          className="activity-persisted-header"
          style={{ color: textColor }}
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
        >
          <StepIcon status={hasError ? 'error' : 'done'} color={hasError ? '#e5683f' : accentColor} />
          <span className="activity-persisted-summary">{activitySummary(steps)}</span>
          <span className={`activity-chevron ${expanded ? 'open' : ''}`} aria-hidden>▸</span>
        </button>
        {expanded && (
          <div className="activity-persisted-steps">
            {steps.map((step) => (
              <div key={step.id} className="activity-step">
                <span className="activity-step-icon">
                  <StepIcon status={step.status} color={step.status === 'error' ? '#e5683f' : accentColor} />
                </span>
                <span className="activity-step-label" style={{ color: textColor, opacity: 0.8 }}>{step.label}</span>
                {step.detail && <span className="activity-step-detail" style={{ color: textColor }}>{step.detail}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

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
