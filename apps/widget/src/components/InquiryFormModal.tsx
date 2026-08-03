import React, { useState, useCallback, useEffect, useRef } from 'react';
import { CountrySelect } from './CountrySelect';
import '../styles/inquiry-form.css';

// ── Types ────────────────────────────────────────────────────────────────────

export interface InquiryFormProps {
  isOpen: boolean;
  productName?: string;
  productSku?: string;
  agentId: string;
  conversationId?: string;
  apiUrl: string;
  /** Called with the success message after the inquiry is delivered */
  onSuccess: (message: string) => void;
  /** Called when the user clicks Skip */
  onSkip: () => void;
  /** When true, renders as an inline chat card (no overlay backdrop) */
  inline?: boolean;
}

interface FormValues {
  name: string;
  phone: string;
  email: string;
  city: string;
  country: string;
  query: string;
}

interface FormErrors {
  name?: string;
  phone?: string;
  email?: string;
  city?: string;
  country?: string;
}

// ── Validation helpers ────────────────────────────────────────────────────────

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Allows +, -, spaces, parens; requires 7-15 digits
const PHONE_RE = /^[+\-()\s]*(\d[+\-()\s]*){7,15}$/;
const DIGITS_ONLY_RE = /^[0-9+\-()\s]+$/;

function validatePhone(value: string): string | undefined {
  if (!value.trim()) return 'Phone is required.';
  if (!DIGITS_ONLY_RE.test(value)) return 'Only digits, +, -, spaces and ( ) allowed.';
  const digits = value.replace(/\D/g, '');
  if (digits.length !== 10) return 'Phone must be exactly 10 digits.';
  return undefined;
}

function validateEmail(value: string): string | undefined {
  if (!value.trim()) return 'Email is required.';
  if (!EMAIL_RE.test(value)) return 'Enter a valid email address.';
  return undefined;
}

function validateRequired(value: string, label: string): string | undefined {
  if (!value.trim()) return `${label} is required.`;
  return undefined;
}

function allRequiredValid(values: FormValues, errors: FormErrors): boolean {
  return (
    !errors.name &&
    !errors.phone &&
    !errors.email &&
    !errors.city &&
    !errors.country &&
    values.name.trim() !== '' &&
    values.phone.trim() !== '' &&
    values.email.trim() !== '' &&
    values.city.trim() !== '' &&
    values.country.trim() !== ''
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export const InquiryFormModal: React.FC<InquiryFormProps> = ({
  isOpen,
  productName,
  productSku,
  agentId,
  conversationId,
  apiUrl,
  onSuccess,
  onSkip,
  inline = false,
}) => {
  const [values, setValues] = useState<FormValues>({
    name: '', phone: '', email: '', city: '', country: '', query: '',
  });
  const [errors, setErrors] = useState<FormErrors>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');

  const firstInputRef = useRef<HTMLInputElement>(null);

  // Focus first input when modal opens
  useEffect(() => {
    if (isOpen && !succeeded) {
      setTimeout(() => firstInputRef.current?.focus(), 80);
    }
  }, [isOpen, succeeded]);

  // Reset form state when modal opens for a new product
  useEffect(() => {
    if (isOpen) {
      setValues({ name: '', phone: '', email: '', city: '', country: '', query: '' });
      setErrors({});
      setTouched({});
      setSubmitting(false);
      setSubmitError(null);
      setSucceeded(false);
    }
  }, [isOpen, productName]);

  // Trap Escape key
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onSkip(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onSkip]);

  const validate = useCallback((field: keyof FormValues, value: string): FormErrors => {
    switch (field) {
      case 'name':    return { name:    validateRequired(value, 'Name') };
      case 'phone':   return { phone:   validatePhone(value) };
      case 'email':   return { email:   validateEmail(value) };
      case 'city':    return { city:    validateRequired(value, 'City') };
      case 'country': return { country: validateRequired(value, 'Country') };
      default: return {};
    }
  }, []);

  const handleChange = (field: keyof FormValues) => (value: string) => {
    // Phone: reject non-digit / non-allowed characters live, limit to 10 digits
    if (field === 'phone') {
      const cleaned = value.replace(/[^\d+\-()\s]/g, '');
      // Hard-stop at 10 digits
      const digitsOnly = cleaned.replace(/\D/g, '');
      if (digitsOnly.length > 10) return;
      setValues(prev => ({ ...prev, phone: cleaned }));
      if (touched.phone) {
        setErrors(prev => ({ ...prev, ...validate('phone', cleaned) }));
      }
      return;
    }
    setValues(prev => ({ ...prev, [field]: value }));
    if (touched[field]) {
      setErrors(prev => ({ ...prev, ...validate(field as keyof FormValues, value) }));
    }
  };

  const handleBlur = (field: keyof FormValues) => () => {
    setTouched(prev => ({ ...prev, [field]: true }));
    setErrors(prev => ({ ...prev, ...validate(field, values[field]) }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validate all required fields
    const allTouched: Record<string, boolean> = {
      name: true, phone: true, email: true, city: true, country: true,
    };
    setTouched(allTouched);
    const newErrors: FormErrors = {
      ...validate('name',    values.name),
      ...validate('phone',   values.phone),
      ...validate('email',   values.email),
      ...validate('city',    values.city),
      ...validate('country', values.country),
    };
    setErrors(newErrors);

    if (!allRequiredValid(values, newErrors)) return;

    setSubmitting(true);
    setSubmitError(null);

    try {
      const base = apiUrl.replace(/\/$/, '');
      const res = await fetch(`${base}/api/v1/inquiry/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId,
          conversation_id: conversationId || null,
          product_name: productName || null,
          product_sku: productSku || null,
          name: values.name.trim(),
          phone: values.phone.trim(),
          email: values.email.trim(),
          city: values.city.trim(),
          country: values.country.trim(),
          query: values.query.trim() || null,
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        setSubmitError(data.message || 'Submission failed. Please try again.');
        setSubmitting(false);
        return;
      }

      const msg = data.message || 'Your inquiry has been sent. Our team will reach out soon.';
      setSuccessMessage(msg);
      setSucceeded(true);
      // Notify parent to display success in chat after a short delay
      setTimeout(() => onSuccess(msg), 1400);
    } catch {
      setSubmitError('Network error. Please check your connection and try again.');
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  const canSubmit = allRequiredValid(values, errors) && !submitting;

  const fieldClass = (field: keyof FormErrors) => {
    if (!touched[field]) return 'inq-input';
    if (errors[field]) return 'inq-input error';
    return 'inq-input valid';
  };

  const selectClass = () => {
    if (!touched.country) return 'inq-select';
    if (errors.country) return 'inq-select error';
    return 'inq-select valid';
  };

  const card = (
    <div
      className={`inq-modal${inline ? ' inq-inline' : ''}`}
      onClick={e => e.stopPropagation()}
      role="dialog"
      aria-modal="true"
      aria-label="Request a Quote"
    >
        <div className="inq-header">
          <h2 className="inq-title">Request a Quote</h2>
          <button className="inq-close-btn" onClick={onSkip} aria-label="Close form" type="button">
            ×
          </button>
        </div>

        {productName && (
          <p className="inq-product-name">For: {productName}</p>
        )}

        {/* ── Success state ──────────────────────────── */}
        {succeeded ? (
          <div className="inq-success">
            <div className="inq-success-icon">✓</div>
            <h3 className="inq-success-title">Inquiry Sent!</h3>
            <p className="inq-success-msg">{successMessage}</p>
            <button className="inq-success-close" onClick={onSkip} type="button">
              Continue browsing
            </button>
          </div>
        ) : (
          /* ── Form ──────────────────────────────────── */
          <form className="inq-form" onSubmit={handleSubmit} noValidate>

            {/* Row: Name + Phone */}
            <div className="inq-row">
              <div className="inq-field">
                <label className="inq-label" htmlFor="inq-name">
                  Name <span className="inq-required">*</span>
                </label>
                <input
                  id="inq-name"
                  ref={firstInputRef}
                  type="text"
                  className={fieldClass('name')}
                  placeholder="Your full name"
                  value={values.name}
                  onChange={e => handleChange('name')(e.target.value)}
                  onBlur={handleBlur('name')}
                  autoComplete="name"
                />
                {touched.name && errors.name && (
                  <span className="inq-error-msg">{errors.name}</span>
                )}
              </div>

              <div className="inq-field">
                <label className="inq-label" htmlFor="inq-phone">
                  Phone <span className="inq-required">*</span>
                </label>
                <input
                  id="inq-phone"
                  type="tel"
                  inputMode="tel"
                  className={fieldClass('phone')}
                  placeholder="+91 9000000000"
                  value={values.phone}
                  onChange={e => handleChange('phone')(e.target.value)}
                  onBlur={handleBlur('phone')}
                  autoComplete="tel"
                  maxLength={10}
                />
                {touched.phone && errors.phone && (
                  <span className="inq-error-msg">{errors.phone}</span>
                )}
              </div>
            </div>

            {/* Email */}
            <div className="inq-field">
              <label className="inq-label" htmlFor="inq-email">
                Email <span className="inq-required">*</span>
              </label>
              <input
                id="inq-email"
                type="email"
                className={fieldClass('email')}
                placeholder="you@example.com"
                value={values.email}
                onChange={e => handleChange('email')(e.target.value)}
                onBlur={handleBlur('email')}
                autoComplete="email"
              />
              {touched.email && errors.email && (
                <span className="inq-error-msg">{errors.email}</span>
              )}
            </div>

            {/* Row: City + Country */}
            <div className="inq-row">
              <div className="inq-field">
                <label className="inq-label" htmlFor="inq-city">
                  City <span className="inq-required">*</span>
                </label>
                <input
                  id="inq-city"
                  type="text"
                  className={fieldClass('city')}
                  placeholder="Your city"
                  value={values.city}
                  onChange={e => handleChange('city')(e.target.value)}
                  onBlur={handleBlur('city')}
                  autoComplete="address-level2"
                />
                {touched.city && errors.city && (
                  <span className="inq-error-msg">{errors.city}</span>
                )}
              </div>

              <div className="inq-field">
                <label className="inq-label" htmlFor="inq-country">
                  Country <span className="inq-required">*</span>
                </label>
                <CountrySelect
                  id="inq-country"
                  value={values.country}
                  onChange={val => {
                    handleChange('country')(val);
                    setTouched(prev => ({ ...prev, country: true }));
                    setErrors(prev => ({ ...prev, ...validate('country', val) }));
                  }}
                  className={selectClass().replace('inq-select', '').trim()}
                  required
                />
                {touched.country && errors.country && (
                  <span className="inq-error-msg">{errors.country}</span>
                )}
              </div>
            </div>

            {/* Query (optional) */}
            <div className="inq-field">
              <label className="inq-label" htmlFor="inq-query">
                Your requirement <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 10 }}>(optional)</span>
              </label>
              <textarea
                id="inq-query"
                className="inq-textarea"
                placeholder="e.g. bulk order of 50 units, need pricing and lead time…"
                value={values.query}
                onChange={e => handleChange('query')(e.target.value)}
                rows={3}
              />
            </div>

            {/* Server error */}
            {submitError && (
              <p className="inq-error-msg" style={{ marginBottom: 10 }}>{submitError}</p>
            )}

            <div className="inq-divider" />

            {/* Footer */}
            <div className="inq-footer">
              <button
                type="button"
                className="inq-skip-btn"
                onClick={onSkip}
              >
                Skip
              </button>
              <button
                type="submit"
                className="inq-submit-btn"
                disabled={!canSubmit}
              >
                {submitting ? (
                  <><span className="inq-spinner" />Sending…</>
                ) : (
                  'Submit'
                )}
              </button>
            </div>
          </form>
        )}
      </div>
  );

  if (inline) {
    return card;
  }

  return (
    <div
      className="inq-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Request a Quote"
      onClick={e => { if (e.target === e.currentTarget) onSkip(); }}
    >
      {card}
    </div>
  );
};
