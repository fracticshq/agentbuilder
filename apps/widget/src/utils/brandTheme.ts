import type { BrandMode, BrandTheme, BrandThemeTokens } from '../types';

export const NOVA_LOGO = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAeAHcDASIAAhEBAxEB/8QAGwAAAgMBAQEAAAAAAAAAAAAABQcEBggAAwH/xAA7EAABAwMCBAUBBAYLAAAAAAABAgMEBQYRAAcIEiExEyJBUWFxFCMygRUWJThCUhczNGJydHaCobGz/8QAGAEBAAMBAAAAAAAAAAAAAAAAAAEFBgT/xAAlEQACAQMCBQUAAAAAAAAAAAAAAQIDBREEBhITITFRFWGBwdH/2gAMAwEAAhEDEQA/AKpxp7JxaDWKhf1ltNKpKnwmtwmSP2dIWEqC+UfhbWFpOP4Sr2IAy7rW++m5srbbi6uB5+Kmp27U4USLWqW55m5UdTCAfKenOATjPuR2J0n+IPbCJZ0yDdVoyjVLDuAePSJyeobJyTHWe4WnBxnBIBz1SoAAnaECC5wfXvUXIUZc1q4oaG5CmklxCSEZSFYyAfbSV087N/cuvv8A1LC/6RpMUSEqpVmDTkq5VSpDbAV7FSgnP/OgHHtlYFn2zYTG627zch+ky1qboNAYWUP1VaehcUQQUND3yM9+xSFnqbxBbq8ihtvYtEtyjIyGo9KonOnlH8yyMKV8gDPtqVxDRWLi4oIW36klu3rZgx4MSMFYSGkx0vKH1JUEk9yEj2Gr5HZajsIYYaQ002kJQhCcJSB2AA7DUmQ3Jun0ipGjThxSaz17JdvoWsbdqz78nfq7vtYVPhPOKCEXBSIpiTYaj0CnUdfESM5I7AfwKOlbvRtxVdsrwVRJz7U6HIaEqm1Bn+qmR1fhcT7H0IycH1IIJbu+9uwqpZcqqFlCZ1PAcbeAwooyApBPqMEn6j66EXG85d3BTQavUPvJtpXM5SIzy+qjFcZS5yfQFTYHw2NQWlhvMbvpeco8LTw17/hH4cKdTr9sK+9rX4MVdbkwv0tQJBaT4wks4KmUrIyAsBIxntznSLWlSFlC0lKknBBGCDqx7YXZMsXcCiXbB5i7TZaHlISrHit9nG8+ykFSfz1eOLK04dubtSKnRQhdAuVhFapbracNqbeHMoJ+ArmIHoCnQuyvbBWQvcLdih20pKvsbj/jT1gdERm/O4SfTIHKD7qGvu/9zUu7d2q7VaFChw6Ol/7NAbiNJbbLLfkSsBIA8+Cv/dpi7SgbbcOF3bluHwq1cpNvUFX4VpbP9odQe/oeo7KaA9dZ+0ATtShzrluemW9TEc8ypSm4rIwSApagkE49BnJPoAdP3jH2zt62Kdblw2Yph6mREfq7U1s9xNjAjmX/AH1JSrP+D50J4Vo0e0qRd29dUaSWbYhKjUhLo8j9QfTyJT7nCVAEDsHAfTUjhpnq3Aot77PVuV4si52F1OlPPq6N1JrKyr3ysAEkejZ9zoDPuu16SGXo0hyPIaW288rocQsYUlQOCCPQg67QDv46/wB5Kuf5aJ/4I1B4fdxqRAiTdstxEmXYlfVyOKUfNS5B6Jktk55cHBV9ArrghQ3ipu2m3vvTVLipLEtmI+xHQlElCUuAoaSk5CVKHce+lZoDVF57dVbbPhi3BoFRWmVGXcUF+nz2x91MjqCORxPf6EZOCD3GCcuRX3YspqSwrkdaWFoV7KByDpssbv1SqcO1U2srYemJiOR36XKKgSyyh1IUyrPUpGRynrjqOwGFDoDSfEa+45ddrcQlsNCTSLhisibyHIYmNt+E6wv+XKE8o+Uq/MtRNx7OqkJMkVqNEUR5mZaw0tJ9uvQ/kTpQbNbt1KwGZ9En0uLclpVUctRok0/dOdvOg4PhudB5sHsMjISQ57M2T2Z3Wi/py0Jl5W4wsnxIclLDyG1eyDzFXKO3mJJ0M9e9t6W7uM6jcZLplePDKBvDf1JrFuLoFtz0TZMl9DbyG2nCVJzkBB5cHKgB0P0zqfvXE/o24erQ2plrbTcNSnKuKtR045opUjkabX7K5SAfls+mMlKvXNq9hawtqzrVq1x3owMs1S4HG/s8JRHRbTTZ8x+uCPRXprP113BWLpuGbcFfnuz6lNcLj77h6qPYAegAAAAHQAADoNDttNpoWrT8ijlrOcvu38YBetHW/TJm9PDFCodPaMy7rGqjUeMjPM49AlLCAkeuEqx8BLPzrOOmlwy7myNrNwnq2GHZcJ+nSGZUZCgPEwguIPXp0WhPX2KvfQtCw8XlUhU+v2/tXRHkuUmyaaiGso/C7MWAp9z6nygjJwrm+dI5pC3XEtNIUtayEpSkZKiewA99Sa1UptYrE2r1F9T82a+uRIdV3W4tRQo/mSdXTh9mW7S914PW7pjTJVMpbhmqYioSpbjjfVsYUpIwF8pPXsMaAv8AxIrTYO3Fl7Jw1JRJhMCs3EEnJVOeB5UEjvyJKh9Cj20mLMuCdal20m5aYrEymS25TQJICihQPKcehxgj1BOvfcO5516XxWbqqKlGRU5a3yknPhpJ8iB8JSEpHwBoDoB08XNAgM33Av6go/YN7QUVeMQOiHlAeO2T/MFEKPsV49Ndrwo93Uy4eGyRt9XWphqFEqqZtClNNpUhtDhPitLyoEDzOKGAckjPbXaA/9k=";


/** Lighten a hex color by mixing with white */
function hexAlpha(hex: string, alpha: number): string {
  // Return rgba string from hex + alpha
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function deriveTokens(primaryColor: string, mode: BrandMode, darkBg?: string, lightBg?: string): BrandThemeTokens {
  const a = primaryColor;

  if (mode === 'dark') {
    return {
      mode,
      panelBg: darkBg || `linear-gradient(160deg,#080d14 0%,#0d1520 30%,#0a1a12 60%,#061008 100%)`,
      sceneBorder: '#1e1e1e',
      sceneShad: '0 20px 60px rgba(0,0,0,0.6)',
      bubbleBg: '#111',
      bubbleBorder: hexAlpha(a, 0.2),
      bubbleShad: `0 6px 24px ${hexAlpha(a, 0.25)}, 0 2px 8px rgba(0,0,0,0.5)`,
      bubbleRing: hexAlpha(a, 0.35),
      orbBg: `radial-gradient(circle,${hexAlpha(a, 0.13)} 0%,transparent 70%)`,
      titleColor: '#ffffff',
      subtitleColor: 'rgba(255,255,255,0.45)',
      accentColor: a,
      chipBg: hexAlpha(a, 0.1),
      chipBorder: hexAlpha(a, 0.2),
      chipColor: 'rgba(255,255,255,0.6)',
      inputBg: 'rgba(255,255,255,0.06)',
      inputBorder: 'rgba(255,255,255,0.1)',
      inputColor: 'rgba(255,255,255,0.38)',
      dividerColor: 'rgba(255,255,255,0.1)',
      voiceBg: 'rgba(255,255,255,0.08)',
      voiceBorder: 'rgba(255,255,255,0.12)',
      voiceIconColor: 'rgba(255,255,255,0.6)',
      sendBg: `linear-gradient(135deg,${a},${hexAlpha(a, 0.7)})`,
      sendShad: `0 4px 14px ${hexAlpha(a, 0.4)}`,
      userMsgBg: a,
      userMsgColor: '#ffffff',
      assistantMsgBg: 'rgba(255,255,255,0.08)',
      assistantMsgColor: 'rgba(255,255,255,0.88)',
    };
  } else {
    return {
      mode,
      panelBg: lightBg || `linear-gradient(160deg,#fdfaf5 0%,#f5f0e8 35%,#ede8df 100%)`,
      sceneBorder: '#e8e0d8',
      sceneShad: '0 20px 60px rgba(0,0,0,0.1)',
      bubbleBg: '#ffffff',
      bubbleBorder: hexAlpha(a, 0.2),
      bubbleShad: `0 6px 24px ${hexAlpha(a, 0.2)}, 0 2px 8px rgba(0,0,0,0.08)`,
      bubbleRing: hexAlpha(a, 0.25),
      orbBg: `radial-gradient(circle,${hexAlpha(a, 0.07)} 0%,transparent 70%)`,
      titleColor: '#1a1208',
      subtitleColor: 'rgba(60,40,20,0.5)',
      accentColor: a,
      chipBg: hexAlpha(a, 0.07),
      chipBorder: hexAlpha(a, 0.18),
      chipColor: hexAlpha(a, 0.85),
      inputBg: 'rgba(255,255,255,0.85)',
      inputBorder: hexAlpha(a, 0.2),
      inputColor: 'rgba(60,40,20,0.45)',
      dividerColor: 'rgba(0,0,0,0.1)',
      voiceBg: hexAlpha(a, 0.07),
      voiceBorder: hexAlpha(a, 0.18),
      voiceIconColor: hexAlpha(a, 0.75),
      sendBg: `linear-gradient(135deg,${a},${hexAlpha(a, 0.75)})`,
      sendShad: `0 4px 14px ${hexAlpha(a, 0.3)}`,
      userMsgBg: a,
      userMsgColor: '#ffffff',
      assistantMsgBg: 'rgba(0,0,0,0.05)',
      assistantMsgColor: '#1a1208',
    };
  }
}

/** Build a BrandTheme from the raw Brand.colors object fetched from admin */
export function buildBrandTheme(
  brandName: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  colors: any
): BrandTheme {
  const primaryColor = colors?.primary_color || '#6366f1';
  const mode: BrandMode = colors?.default_mode === 'light' ? 'light' : 'dark';
  const chips: string[] = colors?.suggestion_chips
    ? colors.suggestion_chips.split(',').map((c: string) => c.trim()).filter(Boolean)
    : [];

  const cyclingCategories: string[] | undefined = colors?.cycling_categories
    ? colors.cycling_categories.split(',').map((c: string) => c.trim()).filter(Boolean)
    : undefined;

  return {
    brandName,
    primaryColor,
    mode,
    hideNovaLogo: colors?.hide_nova_logo ?? false,
    chatLogoDarkUrl: colors?.chat_logo_dark_url || undefined,
    chatLogoLightUrl: colors?.chat_logo_light_url || undefined,
    heroTitle: colors?.hero_title || `I'm ${brandName} AI`,
    heroSubtitle: colors?.hero_subtitle || 'How can I help you today?',
    suggestionChips: chips,
    cyclingCategories,
    darkBgGradient: colors?.dark_bg_gradient || undefined,
    lightBgGradient: colors?.light_bg_gradient || undefined,
    tokens: deriveTokens(primaryColor, mode, colors?.dark_bg_gradient, colors?.light_bg_gradient),
  };
}
