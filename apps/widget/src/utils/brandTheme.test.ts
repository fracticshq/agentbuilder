import { describe, it, expect } from 'vitest';
import { buildBrandTheme } from './brandTheme';

describe('buildBrandTheme', () => {
  it('returns correct defaults when colors is empty', () => {
    const theme = buildBrandTheme('TestBrand', {});

    expect(theme.brandName).toBe('TestBrand');
    expect(theme.primaryColor).toBe('#6366f1');
    expect(theme.mode).toBe('dark');
    expect(theme.heroTitle).toBe("I'm TestBrand AI");
    expect(theme.heroSubtitle).toBe('How can I help you today?');
    expect(theme.suggestionChips).toEqual([]);
    expect(theme.chatLogoDarkUrl).toBeUndefined();
    expect(theme.chatLogoLightUrl).toBeUndefined();
    expect(theme.tokens).toBeDefined();
    expect(theme.tokens.mode).toBe('dark');
  });

  it('respects primary_color and default_mode from colors', () => {
    const theme = buildBrandTheme('Usha', {
      primary_color: '#cc0000',
      default_mode: 'light',
    });

    expect(theme.primaryColor).toBe('#cc0000');
    expect(theme.mode).toBe('light');
    expect(theme.tokens.mode).toBe('light');
    expect(theme.tokens.accentColor).toBe('#cc0000');
  });

  it('parses suggestion_chips from comma-separated string', () => {
    const theme = buildBrandTheme('Antara', {
      suggestion_chips: 'Communities, Care services, Book a visit',
    });

    expect(theme.suggestionChips).toEqual([
      'Communities',
      'Care services',
      'Book a visit',
    ]);
  });

  it('handles suggestion_chips with trailing commas and whitespace', () => {
    const theme = buildBrandTheme('Test', {
      suggestion_chips: ' Fans , Cooking ,  , Sewing , ',
    });

    expect(theme.suggestionChips).toEqual(['Fans', 'Cooking', 'Sewing']);
  });

  it('passes through logo URLs', () => {
    const theme = buildBrandTheme('Test', {
      chat_logo_dark_url: 'https://example.com/dark.png',
      chat_logo_light_url: 'https://example.com/light.png',
    });

    expect(theme.chatLogoDarkUrl).toBe('https://example.com/dark.png');
    expect(theme.chatLogoLightUrl).toBe('https://example.com/light.png');
  });

  it('passes through hero text', () => {
    const theme = buildBrandTheme('Antara', {
      hero_title: "Hello, I'm Antara AI",
      hero_subtitle: 'Ask me about senior living',
    });

    expect(theme.heroTitle).toBe("Hello, I'm Antara AI");
    expect(theme.heroSubtitle).toBe('Ask me about senior living');
  });

  it('passes through custom gradients', () => {
    const darkGrad = 'linear-gradient(160deg,#100000 0%,#1a0000 100%)';
    const lightGrad = 'linear-gradient(160deg,#fff9f7 0%,#ffe8e3 100%)';

    const theme = buildBrandTheme('Custom', {
      dark_bg_gradient: darkGrad,
      light_bg_gradient: lightGrad,
      default_mode: 'dark',
    });

    expect(theme.darkBgGradient).toBe(darkGrad);
    expect(theme.lightBgGradient).toBe(lightGrad);
    // In dark mode, the custom gradient should be used as panelBg
    expect(theme.tokens.panelBg).toBe(darkGrad);
  });

  it('uses light gradient when mode is light', () => {
    const lightGrad = 'linear-gradient(160deg,#fff 0%,#eee 100%)';
    const theme = buildBrandTheme('Custom', {
      light_bg_gradient: lightGrad,
      default_mode: 'light',
    });

    expect(theme.tokens.panelBg).toBe(lightGrad);
  });

  describe('dark mode tokens', () => {
    it('produces expected dark token structure', () => {
      const theme = buildBrandTheme('T', { primary_color: '#00c864', default_mode: 'dark' });
      const tk = theme.tokens;

      expect(tk.mode).toBe('dark');
      expect(tk.titleColor).toBe('#ffffff');
      expect(tk.accentColor).toBe('#00c864');
      expect(tk.userMsgBg).toBe('#00c864');
      expect(tk.userMsgColor).toBe('#ffffff');
      expect(tk.bubbleBg).toBe('#111');
      expect(tk.assistantMsgBg).toContain('rgba');
      expect(tk.sendBg).toContain('#00c864');
    });
  });

  describe('light mode tokens', () => {
    it('produces expected light token structure', () => {
      const theme = buildBrandTheme('T', { primary_color: '#d44a28', default_mode: 'light' });
      const tk = theme.tokens;

      expect(tk.mode).toBe('light');
      expect(tk.titleColor).toBe('#1a1208');
      expect(tk.accentColor).toBe('#d44a28');
      expect(tk.userMsgBg).toBe('#d44a28');
      expect(tk.bubbleBg).toBe('#ffffff');
      expect(tk.sendBg).toContain('#d44a28');
    });
  });

  describe('cyclingCategories', () => {
    it('parses cycling_categories from comma-separated string', () => {
      const theme = buildBrandTheme('Test', {
        cycling_categories: 'Senior living,Memory care,Dining',
      });

      expect(theme.cyclingCategories).toEqual(['Senior living', 'Memory care', 'Dining']);
    });

    it('trims whitespace from cycling categories', () => {
      const theme = buildBrandTheme('Test', {
        cycling_categories: ' Senior living , Memory care , Dining ',
      });

      expect(theme.cyclingCategories).toEqual(['Senior living', 'Memory care', 'Dining']);
    });

    it('filters out empty entries from cycling categories', () => {
      const theme = buildBrandTheme('Test', {
        cycling_categories: 'Senior living,,Dining,',
      });

      expect(theme.cyclingCategories).toEqual(['Senior living', 'Dining']);
    });

    it('returns undefined when cycling_categories is empty string', () => {
      const theme = buildBrandTheme('Test', { cycling_categories: '' });
      expect(theme.cyclingCategories).toBeUndefined();
    });

    it('returns undefined when cycling_categories is not set', () => {
      const theme = buildBrandTheme('Test', {});
      expect(theme.cyclingCategories).toBeUndefined();
    });

    it('returns undefined when colors is null', () => {
      const theme = buildBrandTheme('Test', null);
      expect(theme.cyclingCategories).toBeUndefined();
    });
  });

  it('handles null/undefined colors gracefully', () => {
    expect(() => buildBrandTheme('Test', null)).not.toThrow();
    expect(() => buildBrandTheme('Test', undefined)).not.toThrow();

    const theme = buildBrandTheme('Test', null);
    expect(theme.primaryColor).toBe('#6366f1');
    expect(theme.mode).toBe('dark');
  });

  describe('hideNovaLogo', () => {
    it('defaults to false when hide_nova_logo is not set', () => {
      const theme = buildBrandTheme('Test', {});
      expect(theme.hideNovaLogo).toBe(false);
    });

    it('sets hideNovaLogo to true when hide_nova_logo is true', () => {
      const theme = buildBrandTheme('Test', { hide_nova_logo: true });
      expect(theme.hideNovaLogo).toBe(true);
    });

    it('sets hideNovaLogo to false when hide_nova_logo is explicitly false', () => {
      const theme = buildBrandTheme('Test', { hide_nova_logo: false });
      expect(theme.hideNovaLogo).toBe(false);
    });

    it('defaults to false when colors is null', () => {
      const theme = buildBrandTheme('Test', null);
      expect(theme.hideNovaLogo).toBe(false);
    });
  });
});
