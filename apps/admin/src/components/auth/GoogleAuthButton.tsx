import React from 'react';

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (
            element: HTMLElement,
            options: Record<string, unknown>,
          ) => void;
        };
      };
    };
  }
}

const GOOGLE_SCRIPT_ID = 'google-identity-services';

function loadGoogleScript(): Promise<void> {
  if (document.getElementById(GOOGLE_SCRIPT_ID)) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.id = GOOGLE_SCRIPT_ID;
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Google sign-in'));
    document.head.appendChild(script);
  });
}

interface GoogleAuthButtonProps {
  clientId: string;
  disabled?: boolean;
  onCredential: (credential: string) => void;
}

export function GoogleAuthButton({ clientId, disabled = false, onCredential }: GoogleAuthButtonProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [error, setError] = React.useState<string>('');

  React.useEffect(() => {
    let cancelled = false;

    if (!clientId || disabled) {
      return;
    }

    void loadGoogleScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.google?.accounts?.id) {
          return;
        }

        containerRef.current.innerHTML = '';
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => {
            if (response.credential) {
              onCredential(response.credential);
            }
          },
        });
        window.google.accounts.id.renderButton(containerRef.current, {
          theme: 'outline',
          size: 'large',
          width: 360,
          shape: 'pill',
          text: 'continue_with',
        });
      })
      .catch((scriptError: Error) => {
        if (!cancelled) {
          setError(scriptError.message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [clientId, disabled, onCredential]);

  if (!clientId) {
    return null;
  }

  return (
    <div className="space-y-2">
      <div className={disabled ? 'pointer-events-none opacity-60' : ''} ref={containerRef} />
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}

