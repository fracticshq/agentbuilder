jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: jest.fn(() => ({
      interceptors: {
        request: { use: jest.fn() },
        response: { use: jest.fn() },
      },
      post: jest.fn(),
      get: jest.fn(),
    })),
  },
}));

import {
  AUTH_SESSION_CHANGED_EVENT,
  clearStoredAuthSession,
  createAuthSession,
  getAccessToken,
  getStoredAuthSession,
  isAuthenticated,
  setStoredAuthSession,
  type AuthTokenResponse,
} from './api/client';

const tokenResponse: AuthTokenResponse = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  token_type: 'bearer',
  expires_in: 1800,
};

beforeEach(() => {
  window.localStorage.clear();
});

test('stores the auth session in local storage', () => {
  setStoredAuthSession(createAuthSession(tokenResponse, null));

  expect(getStoredAuthSession()).toMatchObject({
    accessToken: 'access-token',
    refreshToken: 'refresh-token',
  });
  expect(getAccessToken()).toBe('access-token');
  expect(isAuthenticated()).toBe(true);
});

test('preserves the existing refresh token when a refresh response omits it', () => {
  const session = createAuthSession(
    {
      access_token: 'new-access-token',
      token_type: 'bearer',
      expires_in: 1800,
    },
    null,
    'existing-refresh-token',
  );

  expect(session.refreshToken).toBe('existing-refresh-token');
});

test('clears the stored auth session', () => {
  setStoredAuthSession(createAuthSession(tokenResponse, null));

  clearStoredAuthSession();

  expect(getStoredAuthSession()).toBeNull();
  expect(getAccessToken()).toBe('');
  expect(isAuthenticated()).toBe(false);
});

test('emits a session changed event when auth session updates', () => {
  const listener = jest.fn();
  window.addEventListener(AUTH_SESSION_CHANGED_EVENT, listener);

  setStoredAuthSession(createAuthSession(tokenResponse, null));

  expect(listener).toHaveBeenCalledTimes(1);
  expect(listener.mock.calls[0][0]).toBeInstanceOf(CustomEvent);

  window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, listener);
});
