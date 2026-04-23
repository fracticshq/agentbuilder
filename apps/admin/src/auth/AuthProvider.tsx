import React from 'react';

import {
  authApi,
  type AuthRequest,
  type AuthUser,
  clearStoredAuthSession,
  createAuthSession,
  getStoredAuthSession,
  setStoredAuthSession,
  updateStoredAuthUser,
} from '../api/client';
import { ApiError } from '../api/errorHandler';

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  login: (request: AuthRequest) => Promise<void>;
  signup: (request: AuthRequest) => Promise<void>;
  loginWithGoogle: (credential: string) => Promise<void>;
  logout: () => Promise<void>;
  forgotPassword: (email: string) => Promise<{ message: string; resetUrl?: string | null }>;
  resetPassword: (token: string, newPassword: string) => Promise<string>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

async function hydrateAuthenticatedUser() {
  const meResponse = await authApi.me();
  const user = meResponse.data;
  updateStoredAuthUser(user);
  return user;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthStatus>('loading');
  const [user, setUser] = React.useState<AuthUser | null>(null);

  const refreshProfile = React.useCallback(async () => {
    const session = getStoredAuthSession();
    if (!session?.accessToken) {
      clearStoredAuthSession();
      setUser(null);
      setStatus('anonymous');
      return;
    }

    try {
      const authenticatedUser = await hydrateAuthenticatedUser();
      setUser(authenticatedUser);
      setStatus('authenticated');
    } catch {
      clearStoredAuthSession();
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  React.useEffect(() => {
    void refreshProfile();
  }, [refreshProfile]);

  const completeAuth = React.useCallback(async (accessTokenResponse: Awaited<ReturnType<typeof authApi.login>>['data']) => {
    const session = createAuthSession(accessTokenResponse, null);
    setStoredAuthSession(session);
    const authenticatedUser = await hydrateAuthenticatedUser();
    setUser(authenticatedUser);
    setStatus('authenticated');
  }, []);

  const login = React.useCallback(async (request: AuthRequest) => {
    const response = await authApi.login(request);
    await completeAuth(response.data);
  }, [completeAuth]);

  const signup = React.useCallback(async (request: AuthRequest) => {
    await authApi.register(request);
    const response = await authApi.login(request);
    await completeAuth(response.data);
  }, [completeAuth]);

  const loginWithGoogle = React.useCallback(async (credential: string) => {
    const response = await authApi.google(credential);
    await completeAuth(response.data);
  }, [completeAuth]);

  const logout = React.useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort logout; local session is the source of truth for the UI.
    } finally {
      clearStoredAuthSession();
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const forgotPassword = React.useCallback(async (email: string) => {
    const response = await authApi.forgotPassword(email);
    return {
      message: response.data.message,
      resetUrl: response.data.reset_url ?? null,
    };
  }, []);

  const resetPassword = React.useCallback(async (token: string, newPassword: string) => {
    const response = await authApi.resetPassword(token, newPassword);
    return response.data.message;
  }, []);

  const value = React.useMemo<AuthContextValue>(() => ({
    status,
    user,
    login,
    signup,
    loginWithGoogle,
    logout,
    forgotPassword,
    resetPassword,
    refreshProfile,
  }), [status, user, login, signup, loginWithGoogle, logout, forgotPassword, resetPassword, refreshProfile]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}

export function useRequireAuthStatus(): boolean {
  return useAuth().status === 'authenticated';
}

export function isApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Something went wrong. Please try again.';
}

