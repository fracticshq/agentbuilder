import React, { useState, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Dialog } from '@headlessui/react';
import { XMarkIcon, LinkIcon, ArrowUpTrayIcon, XCircleIcon } from '@heroicons/react/24/outline';
import { brandApi, type Brand, type CreateBrandRequest, type BrandIdentity } from '../api/client';

// ── LogoInput ─────────────────────────────────────────────────
// Supports both URL entry and local file upload (stored as base64).
interface LogoInputProps {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  previewBg?: string; // background to show logo preview on
}

function LogoInput({ label, hint, value, onChange, previewBg = '#f3f4f6' }: LogoInputProps) {
  const [mode, setMode] = useState<'url' | 'upload'>(
    value.startsWith('data:') ? 'upload' : 'url'
  );
  const fileRef = useRef<HTMLInputElement>(null);

  // When switching to URL mode, clear any base64 value
  const switchMode = (next: 'url' | 'upload') => {
    if (next === 'url' && value.startsWith('data:')) onChange('');
    setMode(next);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') onChange(reader.result);
    };
    reader.readAsDataURL(file);
  };

  const clear = () => {
    onChange('');
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        {/* Tab toggle */}
        <div className="flex rounded-md overflow-hidden border border-gray-200 text-xs">
          <button
            type="button"
            onClick={() => switchMode('url')}
            className={`flex items-center gap-1 px-2.5 py-1 ${
              mode === 'url'
                ? 'bg-primary-600 text-white'
                : 'bg-white text-gray-500 hover:bg-gray-50'
            }`}
          >
            <LinkIcon className="h-3 w-3" /> URL
          </button>
          <button
            type="button"
            onClick={() => switchMode('upload')}
            className={`flex items-center gap-1 px-2.5 py-1 border-l border-gray-200 ${
              mode === 'upload'
                ? 'bg-primary-600 text-white'
                : 'bg-white text-gray-500 hover:bg-gray-50'
            }`}
          >
            <ArrowUpTrayIcon className="h-3 w-3" /> Upload
          </button>
        </div>
      </div>

      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}

      {mode === 'url' ? (
        <div className="relative">
          <input
            type="url"
            value={value.startsWith('data:') ? '' : value}
            onChange={e => onChange(e.target.value)}
            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm pr-8"
            placeholder="https://example.com/logo.png"
          />
          {value && !value.startsWith('data:') && (
            <button
              type="button"
              onClick={clear}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              aria-label="Clear"
            >
              <XCircleIcon className="h-4 w-4" />
            </button>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <label className="flex-1 cursor-pointer">
            <div className="flex items-center justify-center gap-2 rounded-md border-2 border-dashed border-gray-300 hover:border-primary-400 px-4 py-2.5 text-sm text-gray-500 hover:text-primary-600 transition-colors">
              <ArrowUpTrayIcon className="h-4 w-4" />
              {value.startsWith('data:') ? 'Replace image' : 'Choose image'}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif"
              onChange={handleFile}
              className="sr-only"
            />
          </label>
          {value.startsWith('data:') && (
            <button
              type="button"
              onClick={clear}
              className="text-gray-400 hover:text-red-500 flex-shrink-0"
              aria-label="Remove image"
            >
              <XCircleIcon className="h-5 w-5" />
            </button>
          )}
        </div>
      )}

      {/* Preview */}
      {value && (
        <div
          className="mt-2 inline-flex items-center justify-center rounded p-2"
          style={{ background: previewBg }}
        >
          <img
            src={value}
            alt="preview"
            className="h-8 max-w-[120px] object-contain"
          />
        </div>
      )}
    </div>
  );
}

// ── BrandModal ────────────────────────────────────────────────
interface BrandModalProps {
  isOpen: boolean;
  onClose: () => void;
  brand?: Brand | null;
}

interface FormData {
  name: string;
  description: string;
  industry: string;
  website: string;
  logo_url: string;
  // brand identity
  primary_color: string;
  default_mode: 'dark' | 'light';
  chat_logo_dark_url: string;
  chat_logo_light_url: string;
  hero_title: string;
  hero_subtitle: string;
  suggestion_chips: string;
  cycling_categories: string;
  dark_bg_gradient: string;
  light_bg_gradient: string;
  hide_nova_logo: boolean;
}

const EMPTY_FORM: FormData = {
  name: '',
  description: '',
  industry: '',
  website: '',
  logo_url: '',
  primary_color: '#6366f1',
  default_mode: 'dark',
  chat_logo_dark_url: '',
  chat_logo_light_url: '',
  hero_title: '',
  hero_subtitle: '',
  suggestion_chips: '',
  cycling_categories: '',
  dark_bg_gradient: '',
  light_bg_gradient: '',
  hide_nova_logo: false,
};

export default function BrandModal({ isOpen, onClose, brand }: BrandModalProps) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState<FormData>(EMPTY_FORM);

  const createMutation = useMutation({
    mutationFn: (data: CreateBrandRequest) => brandApi.create(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['brands'] }); onClose(); resetForm(); },
    onError: (err: Error) => { alert(`Failed to create brand: ${err.message}`); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CreateBrandRequest> }) =>
      brandApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['brands'] });
      queryClient.invalidateQueries({ queryKey: ['brand', id] });
      onClose();
      resetForm();
    },
    onError: (err: Error) => { alert(`Failed to update brand: ${err.message}`); },
  });

  const resetForm = () => setFormData(EMPTY_FORM);

  useEffect(() => {
    if (brand) {
      const c = brand.colors || {};
      setFormData({
        name: brand.name,
        description: brand.description,
        industry: brand.industry,
        website: brand.website || '',
        logo_url: brand.logo_url || '',
        primary_color: c.primary_color || '#6366f1',
        default_mode: c.default_mode || 'dark',
        chat_logo_dark_url: c.chat_logo_dark_url || '',
        chat_logo_light_url: c.chat_logo_light_url || '',
        hero_title: c.hero_title || '',
        hero_subtitle: c.hero_subtitle || '',
        suggestion_chips: c.suggestion_chips || '',
        cycling_categories: c.cycling_categories || '',
        dark_bg_gradient: c.dark_bg_gradient || '',
        light_bg_gradient: c.light_bg_gradient || '',
        hide_nova_logo: c.hide_nova_logo ?? false,
      });
    } else {
      resetForm();
    }
  }, [brand]);

  const buildPayload = (): CreateBrandRequest => {
    const identity: BrandIdentity = {
      primary_color: formData.primary_color || undefined,
      default_mode: formData.default_mode,
      chat_logo_dark_url: formData.chat_logo_dark_url || undefined,
      chat_logo_light_url: formData.chat_logo_light_url || undefined,
      hero_title: formData.hero_title || undefined,
      hero_subtitle: formData.hero_subtitle || undefined,
      suggestion_chips: formData.suggestion_chips || undefined,
      cycling_categories: formData.cycling_categories || undefined,
      dark_bg_gradient: formData.dark_bg_gradient || undefined,
      light_bg_gradient: formData.light_bg_gradient || undefined,
      hide_nova_logo: formData.hide_nova_logo || undefined,
    };
    return {
      name: formData.name,
      description: formData.description,
      industry: formData.industry,
      website: formData.website || undefined,
      logo_url: formData.logo_url || undefined,
      colors: identity,
    };
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload = buildPayload();
    if (brand) {
      updateMutation.mutate({ id: brand.id, data: payload });
    } else {
      createMutation.mutate(payload);
    }
  };

  const handleChange = (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) => {
    setFormData(prev => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const isLoading = createMutation.isPending || updateMutation.isPending;
  const accent = formData.primary_color || '#6366f1';

  if (!isOpen) {
    return null;
  }

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/30" aria-hidden="true" />

      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4">
        <Dialog.Panel className="mx-auto max-w-2xl w-full bg-white rounded-lg shadow-xl my-4">
          <div className="flex items-center justify-between p-6 border-b border-gray-200">
            <Dialog.Title className="text-lg font-medium text-gray-900">
              {brand ? 'Edit Brand' : 'Create New Brand'}
            </Dialog.Title>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-500">
              <XMarkIcon className="h-6 w-6" />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="p-6 space-y-6">
            {/* ── Basic Info ── */}
            <div>
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
                Basic Info
              </h3>
              <div className="space-y-4">
                <div>
                  <label htmlFor="name" className="block text-sm font-medium text-gray-700">
                    Brand Name *
                  </label>
                  <input
                    type="text" id="name" name="name" required
                    value={formData.name} onChange={handleChange}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    placeholder="e.g., Antara"
                  />
                </div>

                <div>
                  <label htmlFor="description" className="block text-sm font-medium text-gray-700">
                    Description *
                  </label>
                  <textarea
                    id="description" name="description" required rows={2}
                    value={formData.description} onChange={handleChange}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    placeholder="Brief description of your brand"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="industry" className="block text-sm font-medium text-gray-700">
                      Industry *
                    </label>
                    <select
                      id="industry" name="industry" required
                      value={formData.industry} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    >
                      <option value="">Select an industry</option>
                      <option value="technology">Technology</option>
                      <option value="healthcare">Healthcare</option>
                      <option value="finance">Finance</option>
                      <option value="retail">Retail</option>
                      <option value="manufacturing">Manufacturing</option>
                      <option value="construction">Construction</option>
                      <option value="education">Education</option>
                      <option value="hospitality">Hospitality</option>
                      <option value="senior_living">Senior Living</option>
                      <option value="consumer_appliances">Consumer Appliances</option>
                      <option value="other">Other</option>
                    </select>
                  </div>

                  <div>
                    <label htmlFor="website" className="block text-sm font-medium text-gray-700">
                      Website
                    </label>
                    <input
                      type="url" id="website" name="website"
                      value={formData.website} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                      placeholder="https://example.com"
                    />
                  </div>
                </div>

                <LogoInput
                  label="Brand Logo"
                  hint="Used in the admin interface"
                  value={formData.logo_url}
                  onChange={v => setFormData(prev => ({ ...prev, logo_url: v }))}
                  previewBg="#f3f4f6"
                />
              </div>
            </div>

            {/* ── Widget Identity ── */}
            <div className="border-t border-gray-200 pt-6">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-1">
                Widget Identity
              </h3>
              <p className="text-xs text-gray-500 mb-4">
                Controls how the AI chat widget looks on your website.
              </p>

              <div className="space-y-4">
                {/* Mode + Primary Color row */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Widget Mode
                    </label>
                    <div className="flex gap-3 mt-2">
                      {(['dark', 'light'] as const).map(m => (
                        <label key={m} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="radio" name="default_mode" value={m}
                            checked={formData.default_mode === m}
                            onChange={handleChange}
                            className="text-primary-600 focus:ring-primary-500"
                          />
                          <span className="text-sm text-gray-700 capitalize">{m}</span>
                          <span
                            className="inline-block w-5 h-5 rounded-full border border-gray-300"
                            style={{ background: m === 'dark' ? '#111' : '#f8f8f8' }}
                          />
                        </label>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label htmlFor="primary_color" className="block text-sm font-medium text-gray-700">
                      Primary / Accent Color
                    </label>
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="color" id="primary_color" name="primary_color"
                        value={formData.primary_color} onChange={handleChange}
                        className="h-9 w-12 rounded border border-gray-300 cursor-pointer p-0.5"
                      />
                      <input
                        type="text" name="primary_color"
                        value={formData.primary_color} onChange={handleChange}
                        className="flex-1 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm font-mono"
                        placeholder="#6366f1"
                        maxLength={7}
                      />
                      <span
                        className="h-9 w-9 rounded-lg flex-shrink-0 border border-gray-200"
                        style={{ background: accent }}
                        title="Preview"
                      />
                    </div>
                  </div>
                </div>

                {/* NOVA logo visibility */}
                <div className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-700">Show NOVA logo in widget</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Displays the NOVA platform wordmark in the top-left of the chat panel
                    </p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={!formData.hide_nova_logo}
                    onClick={() => setFormData(prev => ({ ...prev, hide_nova_logo: !prev.hide_nova_logo }))}
                    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 ${
                      !formData.hide_nova_logo ? 'bg-primary-600' : 'bg-gray-200'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                        !formData.hide_nova_logo ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Chat logos */}
                <div className="grid grid-cols-2 gap-4">
                  <LogoInput
                    label="Chat Logo — Dark Mode"
                    hint="Shown in bubble + hero on dark background (white/light asset)"
                    value={formData.chat_logo_dark_url}
                    onChange={v => setFormData(prev => ({ ...prev, chat_logo_dark_url: v }))}
                    previewBg="#111111"
                  />

                  <LogoInput
                    label="Chat Logo — Light Mode"
                    hint="Shown in bubble + hero on light background (dark/colored asset)"
                    value={formData.chat_logo_light_url}
                    onChange={v => setFormData(prev => ({ ...prev, chat_logo_light_url: v }))}
                    previewBg="#f3f3f3"
                  />
                </div>

                {/* Hero text */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="hero_title" className="block text-sm font-medium text-gray-700">
                      Hero Title
                    </label>
                    <input
                      type="text" id="hero_title" name="hero_title"
                      value={formData.hero_title} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                      placeholder="e.g., I'm Antara AI"
                    />
                  </div>

                  <div>
                    <label htmlFor="hero_subtitle" className="block text-sm font-medium text-gray-700">
                      Hero Subtitle
                    </label>
                    <input
                      type="text" id="hero_subtitle" name="hero_subtitle"
                      value={formData.hero_subtitle} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                      placeholder="e.g., Ask me anything about senior living"
                    />
                  </div>
                </div>

                {/* Suggestion chips */}
                <div>
                  <label htmlFor="suggestion_chips" className="block text-sm font-medium text-gray-700">
                    Suggestion Chips
                  </label>
                  <p className="text-xs text-gray-400 mb-1">
                    Comma-separated quick-prompt buttons shown on the landing panel
                  </p>
                  <input
                    type="text" id="suggestion_chips" name="suggestion_chips"
                    value={formData.suggestion_chips} onChange={handleChange}
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    placeholder="e.g., Communities, Care services, Book a visit"
                  />
                  {formData.suggestion_chips && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {formData.suggestion_chips.split(',').map(c => c.trim()).filter(Boolean).map(chip => (
                        <span
                          key={chip}
                          className="px-3 py-1 rounded-full text-xs font-medium border"
                          style={{ background: accent + '18', borderColor: accent + '40', color: accent }}
                        >
                          {chip}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Cycling categories */}
                <div>
                  <label htmlFor="cycling_categories" className="block text-sm font-medium text-gray-700">
                    Cycling Categories
                  </label>
                  <p className="text-xs text-gray-400 mb-1">
                    Comma-separated topics that animate in the subtitle. If set, replaces the static Hero Subtitle line.
                  </p>
                  <input
                    type="text" id="cycling_categories" name="cycling_categories"
                    value={formData.cycling_categories} onChange={handleChange}
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    placeholder="e.g. Senior living, Memory care, Dining, Activities"
                  />
                  {formData.cycling_categories && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {formData.cycling_categories.split(',').map(c => c.trim()).filter(Boolean).map(cat => (
                        <span
                          key={cat}
                          className="px-3 py-1 rounded-full text-xs font-medium border"
                          style={{ background: accent + '18', borderColor: accent + '40', color: accent }}
                        >
                          {cat}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Background gradients */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="dark_bg_gradient" className="block text-sm font-medium text-gray-700">
                      Dark Panel Gradient <span className="text-gray-400">(optional)</span>
                    </label>
                    <input
                      type="text" id="dark_bg_gradient" name="dark_bg_gradient"
                      value={formData.dark_bg_gradient} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm font-mono text-xs"
                      placeholder="linear-gradient(160deg,#100000 0%,#1a0000 100%)"
                    />
                  </div>
                  <div>
                    <label htmlFor="light_bg_gradient" className="block text-sm font-medium text-gray-700">
                      Light Panel Gradient <span className="text-gray-400">(optional)</span>
                    </label>
                    <input
                      type="text" id="light_bg_gradient" name="light_bg_gradient"
                      value={formData.light_bg_gradient} onChange={handleChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm font-mono text-xs"
                      placeholder="linear-gradient(160deg,#fff9f7 0%,#ffe8e3 100%)"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="flex justify-end space-x-3 pt-4 border-t border-gray-200">
              <button
                type="button" onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit" disabled={isLoading}
                className="px-4 py-2 text-sm font-medium text-white bg-primary-600 border border-transparent rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Saving...' : brand ? 'Update Brand' : 'Create Brand'}
              </button>
            </div>
          </form>
        </Dialog.Panel>
        </div>
      </div>
    </Dialog>
  );
}
