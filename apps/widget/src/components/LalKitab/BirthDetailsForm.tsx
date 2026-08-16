import React, { useMemo, useState } from 'react';
import '../../styles/lalkitab-form.css';

export interface PlaceCandidate {
  placeId?: string;
  label?: string;
  name?: string;
  [key: string]: unknown;
}

export interface BirthDetailsFormValues {
  name: string;
  birth_date: string; // YYYY-MM-DD
  birth_time: string; // HH:MM (24h)
  birth_place: string;
  language: string;
}

interface BirthDetailsFormProps {
  agentId: string;
  apiUrl: string;
  sessionToken?: string;
  onGenerated: (payload: { kundaliChart: unknown; apiContext: unknown }) => void;
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export const BirthDetailsForm: React.FC<BirthDetailsFormProps> = ({
  agentId,
  apiUrl,
  sessionToken,
  onGenerated,
}) => {
  const [name, setName] = useState('');
  const [day, setDay] = useState('');
  const [month, setMonth] = useState('');
  const [year, setYear] = useState('');
  const [hour, setHour] = useState('');
  const [minute, setMinute] = useState('');
  const [ampm, setAmpm] = useState<'AM' | 'PM'>('AM');
  const [place, setPlace] = useState('');
  const [manualEntry, setManualEntry] = useState(false);
  const [language, setLanguage] = useState('English');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [placeCandidates, setPlaceCandidates] = useState<PlaceCandidate[]>([]);

  const currentYear = new Date().getFullYear();
  const years = useMemo(() => {
    const list: number[] = [];
    for (let y = currentYear; y >= currentYear - 120; y--) list.push(y);
    return list;
  }, [currentYear]);
  const days = useMemo(() => Array.from({ length: 31 }, (_, i) => i + 1), []);
  const hours = useMemo(() => Array.from({ length: 12 }, (_, i) => i + 1), []);
  const minutes = useMemo(() => Array.from({ length: 60 }, (_, i) => i), []);

  const isValid = Boolean(name.trim() && day && month && year && hour && minute && place.trim());

  const buildBirthDate = (): string => {
    const monthIndex = MONTHS.indexOf(month) + 1;
    return `${year}-${pad2(monthIndex)}-${pad2(Number(day))}`;
  };

  const buildBirthTime = (): string => {
    let h = Number(hour) % 12;
    if (ampm === 'PM') h += 12;
    return `${pad2(h)}:${pad2(Number(minute))}`;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || submitting) return;

    setSubmitting(true);
    setError(null);
    setPlaceCandidates([]);

    try {
      const base = apiUrl.replace(/\/$/, '');
      const res = await fetch(`${base}/api/v1/lalkitab/profile`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionToken ? { 'X-Widget-Session': sessionToken } : {}),
        },
        body: JSON.stringify({
          agent_id: agentId,
          name: name.trim(),
          birth_date: buildBirthDate(),
          birth_time: buildBirthTime(),
          birth_place: place.trim(),
          language: language === 'English' ? 'en' : language,
        }),
      });

      const data = await res.json();
      // A genuine failure (chart/connector unavailable, invalid session,
      // etc.) now comes back as a real non-200 status with FastAPI's
      // HTTPException wrapping the payload under `detail` — the awaiting
      // place-choice / missing-input flow states are still normal 200s with
      // the payload at the top level, so both shapes are checked here.
      const payload = !res.ok && data && typeof data.detail === 'object' && data.detail !== null
        ? data.detail
        : data;

      if (!res.ok || !payload.success) {
        if (payload.awaiting_place_choice && Array.isArray(payload.place_candidates)) {
          setPlaceCandidates(payload.place_candidates);
          setError(payload.message || 'Please confirm which place you were born in.');
        } else {
          // The real upstream status (e.g. Vedika returning 429) is a safe,
          // non-sensitive integer the server now exposes deliberately — show
          // it inline so the actual cause (rate limited vs a genuine outage)
          // is visible without opening dev tools or server logs.
          const upstreamHint = payload.upstream_status_code === 429
            ? ' (the astrology provider is rate-limited right now — please wait a bit and try again)'
            : payload.upstream_status_code
              ? ` (astrology provider returned HTTP ${payload.upstream_status_code})`
              : '';
          setError(
            (payload.message || payload.detail || 'Could not generate your horoscope. Please check your details and try again.')
            + upstreamHint,
          );
        }
        if (!res.ok) {
          // Visible in the console for debugging, without ever logging a
          // provider error, API key, or other connector secret — only the
          // safe error_code + upstream_status_code + request_id the server
          // intentionally exposes.
          console.error(
            '[LalKitab] Birth profile request failed',
            {
              status: res.status,
              errorCode: payload.error_code,
              upstreamStatusCode: payload.upstream_status_code,
              requestId: payload.request_id,
            },
          );
        }
        setSubmitting(false);
        return;
      }

      onGenerated({ kundaliChart: data.kundali_chart, apiContext: data.api_context });
    } catch (err) {
      console.error('[LalKitab] Birth profile network error', err);
      setError('Network error. Please check your connection and try again.');
      setSubmitting(false);
    }
  };

  const handleSelectPlaceCandidate = (candidate: PlaceCandidate) => {
    const label = candidate.label || candidate.name || '';
    if (label) setPlace(label);
    setPlaceCandidates([]);
  };

  return (
    <div className="lk-form-screen">
      <h2 className="lk-form-title">Generate Your Horoscope</h2>
      <p className="lk-form-subtitle">
        Enter your birth details once — we&apos;ll build your Lal Kitab chart and you can ask
        anything about it afterward.
      </p>

      {error && <div className="lk-error-banner">{error}</div>}

      {placeCandidates.length > 0 && (
        <div className="lk-place-candidates">
          {placeCandidates.map((candidate, i) => (
            <button
              key={candidate.placeId || i}
              type="button"
              className="lk-place-candidate-btn"
              onClick={() => handleSelectPlaceCandidate(candidate)}
            >
              {candidate.label || candidate.name || 'Unknown place'}
            </button>
          ))}
        </div>
      )}

      <form className="lk-form-card" onSubmit={handleSubmit}>
        <div className="lk-field">
          <label className="lk-label" htmlFor="lk-name">Full Name</label>
          <input
            id="lk-name"
            type="text"
            className="lk-input"
            placeholder="e.g. Arjuna"
            value={name}
            onChange={e => setName(e.target.value)}
            autoComplete="name"
          />
        </div>

        <div className="lk-field">
          <label className="lk-label">Date of Birth</label>
          <div className="lk-triple-row">
            <select className="lk-select" value={day} onChange={e => setDay(e.target.value)} aria-label="Day">
              <option value="">Day</option>
              {days.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <select className="lk-select" value={month} onChange={e => setMonth(e.target.value)} aria-label="Month">
              <option value="">Month</option>
              {MONTHS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <select className="lk-select" value={year} onChange={e => setYear(e.target.value)} aria-label="Year">
              <option value="">Year</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        <div className="lk-field">
          <label className="lk-label">Time of Birth</label>
          <div className="lk-triple-row">
            <select className="lk-select" value={hour} onChange={e => setHour(e.target.value)} aria-label="Hour">
              <option value="">Hour</option>
              {hours.map(h => <option key={h} value={h}>{h}</option>)}
            </select>
            <select className="lk-select" value={minute} onChange={e => setMinute(e.target.value)} aria-label="Minute">
              <option value="">Min</option>
              {minutes.map(m => <option key={m} value={m}>{pad2(m)}</option>)}
            </select>
            <select className="lk-select" value={ampm} onChange={e => setAmpm(e.target.value as 'AM' | 'PM')} aria-label="AM/PM">
              <option value="AM">AM</option>
              <option value="PM">PM</option>
            </select>
          </div>
        </div>

        <div className="lk-field">
          <label className="lk-label">Location</label>
          <input
            type="text"
            className="lk-input"
            placeholder="City, Country"
            value={place}
            onChange={e => setPlace(e.target.value)}
          />
          {!manualEntry && (
            <button
              type="button"
              className="lk-manual-toggle"
              onClick={() => setManualEntry(true)}
            >
              Enter manually
            </button>
          )}
        </div>

        <div className="lk-field">
          <label className="lk-label">Language</label>
          <select className="lk-select" value={language} onChange={e => setLanguage(e.target.value)}>
            <option value="English">English</option>
            <option value="Hindi">Hindi</option>
          </select>
        </div>

        <button type="submit" className="lk-submit-btn" disabled={!isValid || submitting}>
          {submitting ? 'Generating…' : 'Generate Full Horoscope Analysis'}
        </button>
      </form>
    </div>
  );
};
