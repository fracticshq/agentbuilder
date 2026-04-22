jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: jest.fn(() => ({
      interceptors: {
        request: { use: jest.fn() },
        response: { use: jest.fn() },
      },
    })),
  },
}));

import { clearAdminApiKey, getAdminApiKey, setAdminApiKey } from './api/client';

beforeEach(() => {
  clearAdminApiKey();
});

test('stores the admin API key in session storage', () => {
  setAdminApiKey('  secret-key  ');
  expect(getAdminApiKey()).toBe('secret-key');
});

test('clears the admin API key from session storage', () => {
  setAdminApiKey('secret-key');
  clearAdminApiKey();
  expect(getAdminApiKey()).toBe('');
});
