// Cloudflare Turnstile CAPTCHA widget for the authentication forms.
// Self-hosted installs have no bot-risk by default, so the captcha is OFF
// unless VITE_CLOUDFLARE_TURNSTILE_SITE_KEY is configured — see
// docs/self-hosting.md if you expose signup publicly.

import { Turnstile, type TurnstileInstance } from '@marsidev/react-turnstile';
import { useEffect, useRef } from 'react';

interface TurnstileWidgetProps {
  onSuccess: (token: string) => void;
  onError?: () => void;
  /** Fill the container width (Turnstile "flexible" size) instead of the fixed
   *  300px "normal" widget centered. */
  fullWidth?: boolean;
}

/** Token handed to the form when captcha is switched off, so the submit
 *  button (gated on a non-empty token) stays usable. */
export const CAPTCHA_DISABLED_TOKEN = 'captcha-disabled';

export function TurnstileWidget({ onSuccess, onError, fullWidth = false }: TurnstileWidgetProps) {
  const turnstileRef = useRef<TurnstileInstance>(null);

  const siteKey = import.meta.env.VITE_USE_TEST_CAPTCHA === 'true'
    ? '1x00000000000000000000AA'  // Cloudflare's always-passes test key
    : import.meta.env.VITE_CLOUDFLARE_TURNSTILE_SITE_KEY;

  // No site key configured, or explicitly disabled: skip the captcha entirely.
  const disabled = import.meta.env.VITE_DISABLE_CAPTCHA === 'true' || !siteKey;

  useEffect(() => {
    if (disabled) onSuccess(CAPTCHA_DISABLED_TOKEN);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled]);

  if (disabled) return null;

  return (
    <div className={fullWidth ? 'w-full rr-block ph-no-capture' : 'flex justify-center my-4 rr-block ph-no-capture'}>
      <Turnstile
        ref={turnstileRef}
        siteKey={siteKey}
        onSuccess={onSuccess}
        onError={onError}
        onExpire={() => {
          onError?.();
          turnstileRef.current?.reset();
        }}
        options={{ theme: 'dark', size: fullWidth ? 'flexible' : 'normal' }}
      />
    </div>
  );
}
