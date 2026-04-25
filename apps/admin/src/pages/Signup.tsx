import React from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { authApi, type AuthConfigResponse } from '../api/client';
import { GoogleAuthButton } from '../components/auth/GoogleAuthButton';
import { isApiErrorMessage, useAuth } from '../auth/AuthProvider';

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#1e293b,_#020617_60%)] px-6 py-10 text-slate-900">
      <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="hidden rounded-[2rem] border border-white/10 bg-white/5 p-10 text-white shadow-2xl lg:block">
          <p className="text-sm uppercase tracking-[0.35em] text-sky-200">Operator setup</p>
          <h1 className="mt-6 max-w-xl text-5xl font-semibold leading-tight">
            Create your dashboard access and start managing brands and agents.
          </h1>
          <p className="mt-6 max-w-lg text-lg text-slate-200">
            This signup flow is intended for dashboard operators, not end users of the public chat widget.
          </p>
        </section>
        <section className="rounded-[2rem] bg-white p-8 shadow-2xl sm:p-10">
          <div className="mb-8">
            <p className="text-sm font-semibold uppercase tracking-[0.25em] text-slate-500">NOVA Admin</p>
            <h2 className="mt-3 text-3xl font-semibold text-slate-950">{title}</h2>
            <p className="mt-2 text-sm text-slate-500">{subtitle}</p>
          </div>
          {children}
        </section>
      </div>
    </div>
  );
}

export default function Signup() {
  const { signup, loginWithGoogle } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [confirmPassword, setConfirmPassword] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');
  const [authConfig, setAuthConfig] = React.useState<AuthConfigResponse | null>(null);

  React.useEffect(() => {
    void authApi.getConfig().then((response) => setAuthConfig(response.data)).catch(() => {
      setAuthConfig({ signup_enabled: false, google_enabled: false });
    });
  }, []);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    setError('');

    try {
      await signup({ email, password, full_name: fullName });
      navigate('/dashboard', { replace: true });
    } catch (submitError) {
      setError(isApiErrorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleCredential = React.useCallback(async (credential: string) => {
    setSubmitting(true);
    setError('');

    try {
      await loginWithGoogle(credential);
      navigate('/dashboard', { replace: true });
    } catch (submitError) {
      setError(isApiErrorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  }, [loginWithGoogle, navigate]);

  return (
    <AuthShell title="Create account" subtitle="Set up dashboard access for your team.">
      {!authConfig?.signup_enabled ? (
        <div className="rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Public signup is currently closed. Ask an existing administrator to provision access for you.
        </div>
      ) : (
        <form className="space-y-5" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">Full name</span>
            <input
              autoComplete="name"
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Your name"
              type="text"
              value={fullName}
            />
          </label>

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

          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-700">Password</span>
            <input
              autoComplete="new-password"
              className="w-full rounded-2xl border border-slate-200 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Create a strong password"
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

          <button
            className="w-full rounded-2xl bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting}
            type="submit"
          >
            {submitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>
      )}

      {authConfig?.signup_enabled ? (
        <>
          <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-[0.25em] text-slate-400">
            <span className="h-px flex-1 bg-slate-200" />
            <span>or</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>

          <GoogleAuthButton
            clientId={authConfig?.google_client_id || ''}
            disabled={submitting || !authConfig?.google_enabled}
            onCredential={handleGoogleCredential}
          />
        </>
      ) : null}

      <p className="mt-8 text-sm text-slate-500">
        Already have access?{' '}
        <Link className="font-semibold text-sky-700 hover:text-sky-800" to="/login">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}

