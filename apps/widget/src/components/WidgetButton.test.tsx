import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { WidgetButton } from './WidgetButton';
import { useWidgetStore } from '../stores/widgetStore';
import { buildBrandTheme } from '../utils/brandTheme';

function resetStore() {
  useWidgetStore.setState({
    isOpen: false,
    isConnected: false,
    isTyping: false,
    messages: [],
    conversationId: undefined,
    error: undefined,
    config: null,
    isExpanded: false,
    brandTheme: null,
  });
}

describe('WidgetButton', () => {
  beforeEach(() => {
    resetStore();
  });

  it('renders with "Open chat" label when closed', () => {
    render(<WidgetButton onClick={() => {}} />);
    expect(screen.getByLabelText('Open chat')).toBeInTheDocument();
  });

  it('renders with "Close chat" label when open', () => {
    useWidgetStore.setState({ isOpen: true });
    render(<WidgetButton onClick={() => {}} />);
    expect(screen.getByLabelText('Close chat')).toBeInTheDocument();
  });

  it('calls onClick when clicked', () => {
    const handleClick = vi.fn();
    render(<WidgetButton onClick={handleClick} />);
    fireEvent.click(screen.getByRole('button'));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it('shows brand logo image when chatLogoDarkUrl is set (dark mode)', () => {
    const theme = buildBrandTheme('Test', {
      primary_color: '#00c864',
      default_mode: 'dark',
      chat_logo_dark_url: 'https://example.com/logo-dark.png',
    });
    useWidgetStore.setState({ brandTheme: theme });

    render(<WidgetButton onClick={() => {}} />);
    const img = screen.getByAltText('chat');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', 'https://example.com/logo-dark.png');
  });

  it('shows brand logo image for light mode', () => {
    const theme = buildBrandTheme('Test', {
      primary_color: '#cc0000',
      default_mode: 'light',
      chat_logo_light_url: 'https://example.com/logo-light.png',
    });
    useWidgetStore.setState({ brandTheme: theme });

    render(<WidgetButton onClick={() => {}} />);
    const img = screen.getByAltText('chat');
    expect(img).toHaveAttribute('src', 'https://example.com/logo-light.png');
  });

  it('shows generic icon when no logo URL', () => {
    const theme = buildBrandTheme('Test', { primary_color: '#6366f1', default_mode: 'dark' });
    useWidgetStore.setState({ brandTheme: theme });

    render(<WidgetButton onClick={() => {}} />);
    // No <img> should be present
    expect(screen.queryByAltText('chat')).not.toBeInTheDocument();
    // Should still render a button
    expect(screen.getByLabelText('Open chat')).toBeInTheDocument();
  });

  it('applies brand bubble styles', () => {
    const theme = buildBrandTheme('Test', { primary_color: '#ff0000', default_mode: 'dark' });
    useWidgetStore.setState({ brandTheme: theme });

    render(<WidgetButton onClick={() => {}} />);
    const button = screen.getByRole('button');
    // Browser normalizes #111 to rgb(17, 17, 17)
    expect(button.style.background).toBe('rgb(17, 17, 17)');
  });

  it('shows pulse ring when closed, hides when open', () => {
    const theme = buildBrandTheme('Test', { primary_color: '#ff0000', default_mode: 'dark' });
    useWidgetStore.setState({ brandTheme: theme, isOpen: false });

    const { container, rerender } = render(<WidgetButton onClick={() => {}} />);
    expect(container.querySelector('.widget-bubble-ring')).toBeInTheDocument();

    // Now open
    useWidgetStore.setState({ isOpen: true });
    rerender(<WidgetButton onClick={() => {}} />);
    expect(container.querySelector('.widget-bubble-ring')).not.toBeInTheDocument();
  });
});
