import React from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { isApiErrorMessage, useAuth } from '../auth/AuthProvider';

export default function ResetPassword() {
  const { resetPassword } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [password, setPassword] = React.useState('');
  const [confirmPassword, setConfirmPassword] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');
  const [successMessage, setSuccessMessage] = React.useState('');

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!token) {
      setError('This reset link is missing a token.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    setError('');

    try {
      const message = await resetPassword(token, password);
      setSuccessMessage(message);
      window.setTimeout(() => {
        navigate('/login', { replace: true });
      }, 1500);
    } catch (submitError) {
      setError(isApiErrorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-10">
      <div className="w-full max-w-lg rounded-[2rem] bg-white p-8 shadow-2xl sm:p-10">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-500">Password reset</p>
        <h1 className="mt-3 text-3xl font-semibold text-slate-950">Choose a new password</h1>
        <p className="mt-2 text-sm text-slate-500">
          Reset the password for your admin dashboard account.
        </p>

        <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">New password</span>
            <input
              autoComplete="new-password"
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter a strong password"
              type="password"
              value={password}
            />
          </label>

          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">Confirm password</span>
            <input
              autoComplete="new-password"
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Repeat your password"
              type="password"
              value={confirmPassword}
            />
          </label>

          {error ? <p className="rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p> : null}
          {successMessage ? <p className="rounded-2xl bg-green-50 px-4 py-3 text-sm text-green-700">{successMessage}</p> : null}

          <button
            className="w-full rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting}
            type="submit"
          >
            {submitting ? 'Updating password...' : 'Reset password'}
          </button>
        </form>

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

