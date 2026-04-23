import React from 'react';
import { Link } from 'react-router-dom';

import { useAuth } from '../auth/AuthProvider';

export default function ForgotPassword() {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const [resetUrl, setResetUrl] = React.useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setMessage('');
    setResetUrl(null);

    try {
      const result = await forgotPassword(email);
      setMessage(result.message);
      setResetUrl(result.resetUrl || null);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-10">
      <div className="w-full max-w-lg rounded-[2rem] bg-white p-8 shadow-2xl sm:p-10">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-500">Password recovery</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-950">Forgot your password?</h1>
        <p className="mt-2 text-sm text-slate-500">
          Enter your email and we’ll generate reset instructions if your account exists.
        </p>

        <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">Email</span>
            <input
              autoComplete="email"
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
              type="email"
              value={email}
            />
          </label>

          <button
            className="w-full rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting}
            type="submit"
          >
            {submitting ? 'Generating reset link...' : 'Send reset instructions'}
          </button>
        </form>

        {message ? <p className="mt-6 rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">{message}</p> : null}
        {resetUrl ? (
          <p className="mt-4 text-sm text-slate-600">
            Local development reset link:{' '}
            <a className="font-semibold text-sky-700 hover:text-sky-800" href={resetUrl}>
              Open reset page
            </a>
          </p>
        ) : null}

        <p className="mt-8 text-sm text-slate-500">
          Back to{' '}
          <Link className="font-semibold text-sky-700 hover:text-sky-800" to="/login">
            sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

