import { useEffect, useState } from 'react';

import {
  ADMIN_API_KEY_CHANGED_EVENT,
  hasAdminApiKey,
} from '../api/client';

export function useAdminApiKey(): boolean {
  const [isConfigured, setIsConfigured] = useState(() => hasAdminApiKey());

  useEffect(() => {
    const syncState = () => {
      setIsConfigured(hasAdminApiKey());
    };

    window.addEventListener(ADMIN_API_KEY_CHANGED_EVENT, syncState);
    window.addEventListener('storage', syncState);

    return () => {
      window.removeEventListener(ADMIN_API_KEY_CHANGED_EVENT, syncState);
      window.removeEventListener('storage', syncState);
    };
  }, []);

  return isConfigured;
}
