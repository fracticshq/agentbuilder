import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatWindow } from './ChatWindow';
import { useWidgetStore } from '../stores/widgetStore';
import { buildBrandTheme } from '../utils/brandTheme';
import type { Message } from '../types';

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

function setBrand(overrides: Record<string, unknown> = {}) {
  const theme = buildBrandTheme('TestBrand', {
    primary_color: '#00c864',
    default_mode: 'dark',
    hero_title: "I'm TestBrand AI",
    hero_subtitle: 'Ask me about testing',
    suggestion_chips: 'Chip A,Chip B,Chip C',
    ...overrides,
  });
  useWidgetStore.setState({ brandTheme: theme });
  return theme;
}

const noopClose = () => {};
const noopExpand = () => {};

describe('ChatWindow', () => {
  beforeEach(() => {
    resetStore();
  });

  describe('landing state (no messages)', () => {
    it('shows NOVA logo image', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByAltText('NOVA')).toBeInTheDocument();
    });

    it('hides NOVA logo when hideNovaLogo is true', () => {
      setBrand({ hide_nova_logo: true });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.queryByAltText('NOVA')).not.toBeInTheDocument();
    });

    it('shows hero title and subtitle', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText("I'm TestBrand AI")).toBeInTheDocument();
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });

    it('shows suggestion chips', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Chip A')).toBeInTheDocument();
      expect(screen.getByText('Chip B')).toBeInTheDocument();
      expect(screen.getByText('Chip C')).toBeInTheDocument();
    });

    it('clicking a chip fires onSendMessage with chip text', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      fireEvent.click(screen.getByText('Chip B'));
      expect(onSend).toHaveBeenCalledWith('Chip B');
    });

    it('shows brand logo when chatLogoDarkUrl is set', () => {
      setBrand({ chat_logo_dark_url: 'https://example.com/logo.png' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const img = screen.getByAltText('TestBrand');
      expect(img).toHaveAttribute('src', 'https://example.com/logo.png');
    });

    it('shows placeholder initial when no logo', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('T')).toBeInTheDocument(); // first letter of 'TestBrand'
    });

    it('sends message via input on Enter', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.change(input, { target: { value: 'Hello AI' } });
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSend).toHaveBeenCalledWith('Hello AI');
    });

    it('does not send empty message on Enter', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSend).not.toHaveBeenCalled();
    });

    it('sends message via send button click', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.change(input, { target: { value: 'Test message' } });
      fireEvent.click(screen.getByLabelText('Send'));
      expect(onSend).toHaveBeenCalledWith('Test message');
    });

    it('close button calls onClose', () => {
      setBrand();
      const onClose = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={onClose} onToggleExpand={noopExpand} />
      );
      fireEvent.click(screen.getByLabelText('Close chat'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('chat state (messages present)', () => {
    const messages: Message[] = [
      { id: '1', content: 'Hello', role: 'user', timestamp: new Date() },
      { id: '2', content: 'Hi there!', role: 'assistant', timestamp: new Date() },
    ];

    it('renders messages instead of hero', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      // Hero should not be visible
      expect(screen.queryByText("I'm TestBrand AI")).not.toBeInTheDocument();
      // Messages should be visible
      expect(screen.getByText('Hello')).toBeInTheDocument();
    });

    it('still shows NOVA logo in chat state', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByAltText('NOVA')).toBeInTheDocument();
    });

    it('shows typing indicator with dots', () => {
      setBrand();
      const pendingMessages: Message[] = [
        { id: '1', content: 'Hello', role: 'user', timestamp: new Date() },
      ];
      render(
        <ChatWindow messages={pendingMessages} isTyping={true} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const dots = document.querySelectorAll('.typing-dots .dot');
      expect(dots.length).toBe(3);
    });

    it('chat input shows "Type your message..." placeholder', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByPlaceholderText('Type your message...')).toBeInTheDocument();
    });

    it('renders products on a resolved assistant message as product cards', () => {
      setBrand();
      const productMessages: Message[] = [
        { id: '1', content: 'Show me earrings', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'These match your search.',
          role: 'assistant',
          timestamp: new Date(),
          products: [
            {
              sku: 'HD-001',
              name: 'Heart Drop Earrings',
              price: 44900,
              currency: 'USD',
              category: 'Jewelry',
              in_stock: true,
              product_url: 'https://example.com/products/heart-drop-earrings',
            },
          ],
        },
      ];

      render(
        <ChatWindow messages={productMessages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );

      expect(screen.getByText('Product:')).toBeInTheDocument();
      expect(screen.getByText('Heart Drop Earrings')).toBeInTheDocument();
      expect(screen.getByText('SKU: HD-001')).toBeInTheDocument();
      expect(screen.getByText('$449.00')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Learn more about this product' })).toBeInTheDocument();
    });

    it('renders one grouped product card with selectable variants', () => {
      setBrand();
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      const productMessages: Message[] = [
        { id: '1', content: 'Show me Denon Home 150', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'This matches your search.',
          role: 'assistant',
          timestamp: new Date(),
          products: [
            {
              product_group_id: 'shopify:denon-home-150',
              sku: 'DENON-BLK',
              name: 'Denon Home 150 Wireless Speaker',
              price: 4190000,
              currency: 'INR',
              category: 'General',
              in_stock: true,
              product_url: 'https://soundtrails.in/products/denon-home-150-wireless-speaker-1',
              variant_count: 2,
              has_variants: true,
              variants: [
                {
                  variant_id: '49151795560721',
                  variant_sku: 'DENON-BLK',
                  variant_options: { Color: 'Black' },
                  price: 4190000,
                  currency: 'INR',
                  variant_url: 'https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=49151795560721',
                  in_stock: true,
                  is_default: true,
                },
                {
                  variant_id: '49151800443153',
                  variant_sku: 'DENON-WHT',
                  variant_options: { Color: 'White' },
                  price: 4290000,
                  currency: 'INR',
                  variant_url: 'https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=49151800443153',
                  in_stock: true,
                },
              ],
            },
          ],
        },
      ];

      render(
        <ChatWindow messages={productMessages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );

      expect(screen.getByText('Product:')).toBeInTheDocument();
      expect(screen.getAllByText('Denon Home 150 Wireless Speaker')).toHaveLength(1);
      expect(screen.getByText('SKU: DENON-BLK (Black)')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /more variants/i })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /White/ }));
      expect(screen.getByText('SKU: DENON-WHT (White)')).toBeInTheDocument();
      expect(screen.getAllByText('₹42,900.00').length).toBeGreaterThan(0);
      fireEvent.click(screen.getByRole('button', { name: 'Learn more about this product' }));
      expect(openSpy).toHaveBeenCalledWith(
        'https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=49151800443153',
        '_blank',
        'noopener,noreferrer'
      );
      openSpy.mockRestore();
    });

    it('adds the selected variant to the product URL when the catalog omits variant URLs', () => {
      setBrand();
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
      const productMessages: Message[] = [
        { id: '1', content: 'Show me the speaker colours', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'Here are the available colours.',
          role: 'assistant',
          timestamp: new Date(),
          products: [
            {
              product_group_id: 'shopify:speaker',
              sku: 'SPEAKER-BLK',
              name: 'Wireless Speaker',
              price: 4190000,
              currency: 'INR',
              product_url: 'https://soundtrails.in/products/wireless-speaker?ref=chat',
              has_variants: true,
              variants: [
                {
                  variant_id: '49151795560721',
                  variant_options: { Color: 'Black' },
                  price: 4190000,
                  currency: 'INR',
                  is_default: true,
                },
                {
                  variant_id: 'gid://shopify/ProductVariant/49151800443153',
                  variant_options: { Color: 'White' },
                  price: 4290000,
                  currency: 'INR',
                },
              ],
            },
          ],
        },
      ];

      render(
        <ChatWindow messages={productMessages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );

      fireEvent.click(screen.getByRole('button', { name: /White/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Learn more about this product' }));

      expect(openSpy).toHaveBeenCalledWith(
        'https://soundtrails.in/products/wireless-speaker?ref=chat&variant=49151800443153',
        '_blank',
        'noopener,noreferrer'
      );
      openSpy.mockRestore();
    });

    it('expands variant tiles inline when more variants are available', () => {
      setBrand();
      const colors = ['Black', 'White', 'Silver', 'Walnut', 'Blue', 'Red'];
      const productMessages: Message[] = [
        { id: '1', content: 'Show Denon colours', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'Here are the variants.',
          role: 'assistant',
          timestamp: new Date(),
          products: [
            {
              product_group_id: 'shopify:denon-home-150',
              sku: 'DENON-BLK',
              name: 'Denon Home 150 Wireless Speaker',
              price: 4190000,
              currency: 'INR',
              category: 'General',
              in_stock: true,
              product_url: 'https://soundtrails.in/products/denon-home-150-wireless-speaker-1',
              variant_count: colors.length,
              has_variants: true,
              variants: colors.map((color, index) => ({
                variant_id: `variant-${color}`,
                variant_sku: `DENON-${color.toUpperCase()}`,
                variant_options: { Colour: color },
                price: 4190000,
                currency: 'INR',
                variant_url: `https://soundtrails.in/products/denon-home-150-wireless-speaker-1?variant=${index}`,
                in_stock: true,
                is_default: index === 0,
              })),
            },
          ],
        },
      ];

      render(
        <ChatWindow messages={productMessages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );

      expect(screen.getByText('Choose Colour')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /View 2 more variants/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Blue/ })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /View 2 more variants/i }));

      expect(screen.getByRole('button', { name: /Blue/ })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Red/ })).toBeInTheDocument();
    });

    it('renders multi-option variants as full purchasable variant tiles', () => {
      setBrand();
      const productMessages: Message[] = [
        { id: '1', content: 'Show strawberry whey protein', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'Here are matching variants.',
          role: 'assistant',
          timestamp: new Date(),
          products: [
            {
              product_group_id: 'shopify:whey-protein',
              sku: 'WHEY-STRAW-2LB',
              name: 'Gold Standard 100% Whey Protein',
              price: 549900,
              currency: 'INR',
              category: 'Nutrition',
              in_stock: true,
              product_url: 'https://example.com/products/whey',
              variant_count: 2,
              has_variants: true,
              variants: [
                {
                  variant_id: 'strawberry-2lb',
                  variant_sku: 'WHEY-STRAW-2LB',
                  variant_options: { Flavour: 'Strawberry', Weight: '2 lbs (907 g)' },
                  price: 549900,
                  currency: 'INR',
                  variant_url: 'https://example.com/products/whey?variant=strawberry-2lb',
                  in_stock: true,
                  is_default: true,
                },
                {
                  variant_id: 'vanilla-5lb',
                  variant_sku: 'WHEY-VAN-5LB',
                  variant_options: { Flavour: 'Vanilla Ice Cream', Weight: '5 lbs (2.27 kg)' },
                  price: 899900,
                  currency: 'INR',
                  variant_url: 'https://example.com/products/whey?variant=vanilla-5lb',
                  in_stock: true,
                },
              ],
            },
          ],
        },
      ];

      render(
        <ChatWindow messages={productMessages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );

      expect(screen.getByText('Choose Flavour & Weight')).toBeInTheDocument();
      expect(screen.getByText('Strawberry')).toBeInTheDocument();
      expect(screen.getByText('2 lbs (907 g)')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /Vanilla Ice Cream/ }));
      expect(screen.getByText('SKU: WHEY-VAN-5LB (Vanilla Ice Cream)')).toBeInTheDocument();
      expect(screen.getByText('5 lbs (2.27 kg)')).toBeInTheDocument();
    });

    it('does not render citations when showSources is false even if citations exist', () => {
      setBrand();
      const citedMessages: Message[] = [
        { id: '1', content: 'Do you have sourcing?', role: 'user', timestamp: new Date() },
        {
          id: '2',
          content: 'Yes, but sources are disabled for this widget.',
          role: 'assistant',
          timestamp: new Date(),
          citations: [
            {
              doc_id: 'catalog-1',
              title: 'Jewelry Catalog',
              url: 'https://example.com/catalog',
              confidence: 0.91,
              snippet: 'Heart Drop Earrings are listed in the summer catalog.',
            },
          ],
        },
      ];

      render(
        <ChatWindow
          messages={citedMessages}
          isTyping={false}
          onSendMessage={vi.fn()}
          onClose={noopClose}
          onToggleExpand={noopExpand}
          showSources={false}
        />
      );

      expect(screen.queryByText('Sources')).not.toBeInTheDocument();
      expect(screen.queryByText('Jewelry Catalog')).not.toBeInTheDocument();
      expect(screen.queryByText('Heart Drop Earrings are listed in the summer catalog.')).not.toBeInTheDocument();
    });
  });

  describe('cycling subtitle', () => {
    it('shows cycling accent span when cyclingCategories are set', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care,Dining' });
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(container.querySelector('.chat-hero-cycling-text')).toBeInTheDocument();
    });

    it('shows first cycling category as initial text', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care,Dining' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Senior living')).toBeInTheDocument();
    });

    it('does not show cycling row when cyclingCategories is not set', () => {
      setBrand();
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(container.querySelector('.chat-hero-cycling-text')).not.toBeInTheDocument();
    });

    it('shows static subtitle when no cycling categories', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });

    it('shows static subtitle line alongside cycling row when categories are set', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });
  });

  describe('light mode', () => {
    it('uses light mode tokens for panel background', () => {
      setBrand({ default_mode: 'light' });
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const panel = container.querySelector('.chat-panel');
      // Light mode gradient should contain light colors
      expect(panel?.getAttribute('style')).toContain('linear-gradient');
    });
  });
});
