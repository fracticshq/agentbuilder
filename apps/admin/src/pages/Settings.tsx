import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  KeyIcon,
  ShieldCheckIcon,
} from '@heroicons/react/24/outline';
import {
  runtimeSettingsApi,
  type RuntimeSettingField,
  type RuntimeSettingSection,
} from '../api/client';
import { ApiError } from '../api/errorHandler';

type SectionTestState = {
  status: 'idle' | 'testing' | 'healthy' | 'unhealthy';
  message?: string;
};

function formatMaskedValue(maskedValue?: string | null): string {
  if (!maskedValue) {
    return 'Configured';
  }

  const trimmedValue = maskedValue.trim();
  if (trimmedValue.length <= 28) {
    return trimmedValue;
  }

  return `${trimmedValue.slice(0, 12)}...${trimmedValue.slice(-10)}`;
}

function countConfiguredFields(section: RuntimeSettingSection): number {
  return section.fields.filter((field) => field.configured || (field.value || '').trim()).length;
}

function buildInitialDraftValues(sections: RuntimeSettingSection[]): Record<string, string> {
  const next: Record<string, string> = {};
  sections.forEach((section) => {
    section.fields.forEach((field) => {
      next[field.key] = field.secret ? '' : field.value || '';
    });
  });
  return next;
}

export default function Settings() {
  const queryClient = useQueryClient();
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [clearedKeys, setClearedKeys] = useState<Record<string, boolean>>({});
  const [saveMessage, setSaveMessage] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [testStates, setTestStates] = useState<Record<string, SectionTestState>>({});

  const { data, isLoading, error } = useQuery({
    queryKey: ['runtime-settings'],
    queryFn: () => runtimeSettingsApi.get().then((response) => response.data),
  });

  useEffect(() => {
    if (!data?.sections) {
      return;
    }
    setDraftValues(buildInitialDraftValues(data.sections));
    setClearedKeys({});
    setTestStates({});
    setSaveMessage('');
    setSaveState('idle');
  }, [data]);

  const allFields = useMemo(
    () => data?.sections.flatMap((section) => section.fields) || [],
    [data],
  );

  const updateMutation = useMutation({
    mutationFn: (updates: Record<string, string | null>) => runtimeSettingsApi.update(updates),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['runtime-settings'] });
    },
  });

  const buildPendingUpdates = (
    fields: RuntimeSettingField[],
  ): Record<string, string | null> => {
    const updates: Record<string, string | null> = {};

    fields.forEach((field) => {
      const draftValue = (draftValues[field.key] || '').trim();
      const wasCleared = Boolean(clearedKeys[field.key]);

      if (field.secret) {
        if (wasCleared) {
          updates[field.key] = null;
        } else if (draftValue) {
          updates[field.key] = draftValue;
        }
        return;
      }

      const currentValue = (field.value || '').trim();
      if (draftValue !== currentValue) {
        updates[field.key] = draftValue || null;
      }
    });

    return updates;
  };

  const handleFieldChange = (fieldKey: string, value: string) => {
    setDraftValues((current) => ({
      ...current,
      [fieldKey]: value,
    }));

    if (clearedKeys[fieldKey]) {
      setClearedKeys((current) => ({
        ...current,
        [fieldKey]: false,
      }));
    }

    if (saveState !== 'idle') {
      setSaveState('idle');
      setSaveMessage('');
    }
  };

  const handleClearSecret = (fieldKey: string) => {
    setDraftValues((current) => ({
      ...current,
      [fieldKey]: '',
    }));
    setClearedKeys((current) => ({
      ...current,
      [fieldKey]: true,
    }));
  };

  const handleSave = async () => {
    const updates = buildPendingUpdates(allFields);
    if (Object.keys(updates).length === 0) {
      setSaveState('saved');
      setSaveMessage('No settings changes to save.');
      return;
    }

    setSaveState('saving');
    setSaveMessage('Saving runtime settings...');

    try {
      await updateMutation.mutateAsync(updates);
      setSaveState('saved');
      setSaveMessage('Runtime settings saved. New requests will pick up the updated values.');
    } catch (mutationError) {
      const message =
        mutationError instanceof ApiError
          ? mutationError.message
          : 'Could not save runtime settings. Please try again.';
      setSaveState('error');
      setSaveMessage(message);
    }
  };

  const buildSectionOverrides = (section: RuntimeSettingSection): Record<string, string | null> => {
    const overrides: Record<string, string | null> = {};

    section.fields.forEach((field) => {
      const draftValue = (draftValues[field.key] || '').trim();
      const wasCleared = Boolean(clearedKeys[field.key]);

      if (field.secret) {
        if (wasCleared) {
          overrides[field.key] = null;
        } else if (draftValue) {
          overrides[field.key] = draftValue;
        }
        return;
      }

      const currentValue = (field.value || '').trim();
      if (draftValue !== currentValue) {
        overrides[field.key] = draftValue || null;
      }
    });

    return overrides;
  };

  const handleTestConnection = async (section: RuntimeSettingSection) => {
    setTestStates((current) => ({
      ...current,
      [section.id]: {
        status: 'testing',
        message: 'Testing connection...',
      },
    }));

    try {
      const response = await runtimeSettingsApi.test({
        sections: [section.id],
        overrides: buildSectionOverrides(section),
      });
      const result = response.data.results[0];
      setTestStates((current) => ({
        ...current,
        [section.id]: {
          status: result.status,
          message: result.detail,
        },
      }));
    } catch (mutationError) {
      const message =
        mutationError instanceof ApiError
          ? mutationError.message
          : 'Connection test failed unexpectedly.';
      setTestStates((current) => ({
        ...current,
        [section.id]: {
          status: 'unhealthy',
          message,
        },
      }));
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary-600" />
      </div>
    );
  }

  if (error || !data) {
    const message = error instanceof ApiError ? error.message : 'Could not load runtime settings.';
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <div className="flex items-start gap-3">
          <ExclamationTriangleIcon className="mt-0.5 h-6 w-6 text-red-500" />
          <div>
            <h1 className="text-lg font-semibold text-red-900">Runtime settings unavailable</h1>
            <p className="mt-2 text-sm text-red-700">{message}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 rounded-2xl bg-white p-8 shadow-sm ring-1 ring-gray-200 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex items-center gap-3">
            <ShieldCheckIcon className="h-7 w-7 text-primary-600" />
            <h1 className="text-2xl font-bold text-gray-900">Runtime Settings</h1>
          </div>
          <p className="mt-3 text-sm text-gray-600">
            Manage provider credentials and runtime metadata here instead of editing local env files.
            Secret values are encrypted in the system database and only masked values are shown back in the UI.
          </p>
        </div>
        <div className="flex flex-col items-start gap-3 lg:items-end">
          <button
            className="inline-flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-500"
            disabled={saveState === 'saving'}
            onClick={() => void handleSave()}
            type="button"
          >
            {saveState === 'saving' ? <ArrowPathIcon className="h-4 w-4 animate-spin" /> : <KeyIcon className="h-4 w-4" />}
            {saveState === 'saving' ? 'Saving...' : 'Save Settings'}
          </button>
          {saveMessage && (
            <p
              className={`text-sm ${
                saveState === 'saved'
                  ? 'text-green-600'
                  : saveState === 'error'
                    ? 'text-red-600'
                    : 'text-gray-500'
              }`}
            >
              {saveMessage}
            </p>
          )}
        </div>
      </div>

      {data.sections.map((section) => {
        const testState = testStates[section.id] || { status: 'idle' };

        return (
          <section key={section.id} className="rounded-2xl bg-white p-8 shadow-sm ring-1 ring-gray-200">
            <div className="border-b border-gray-100 pb-6">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0 max-w-3xl">
                  <div className="flex flex-wrap items-center gap-3">
                    <h2 className="text-xl font-semibold text-gray-900">{section.title}</h2>
                    <span className="inline-flex rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
                      {countConfiguredFields(section)} configured
                    </span>
                  </div>
                  <p className="mt-2 break-words text-sm leading-6 text-gray-600">
                    {section.description}
                  </p>
                </div>
              </div>

              {section.supports_connection_test && (
                <div className="mt-5 flex flex-col gap-4 rounded-2xl border border-gray-200 bg-gray-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900">Connection test</p>
                    <p className="mt-1 break-words text-sm text-gray-600">
                      Validate the currently saved values for this provider before you leave the page.
                    </p>
                    {testState.message && (
                      <p
                        className={`mt-2 break-words text-sm ${
                          testState.status === 'healthy'
                            ? 'text-green-600'
                            : testState.status === 'unhealthy'
                              ? 'text-red-600'
                              : 'text-gray-500'
                        }`}
                      >
                        {testState.message}
                      </p>
                    )}
                  </div>
                  <button
                    className="inline-flex w-full shrink-0 items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 shadow-sm transition hover:bg-gray-100 sm:w-auto"
                    disabled={testState.status === 'testing'}
                    onClick={() => void handleTestConnection(section)}
                    type="button"
                  >
                    {testState.status === 'testing' ? (
                      <ArrowPathIcon className="h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheckIcon className="h-4 w-4" />
                    )}
                    {testState.status === 'testing' ? 'Testing...' : 'Test Connection'}
                  </button>
                </div>
              )}
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
              {section.fields.map((field) => {
                const configuredSecret = field.secret && field.configured && !clearedKeys[field.key];
                return (
                  <div key={field.key} className="min-w-0 overflow-hidden rounded-2xl border border-gray-200 p-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <label className="text-sm font-semibold text-gray-900" htmlFor={field.key}>
                          {field.label}
                          {field.required ? ' *' : ''}
                        </label>
                        <p className="mt-1 break-words text-sm leading-6 text-gray-500">{field.description}</p>
                      </div>
                      <span
                        className={`inline-flex shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
                          field.source === 'stored'
                            ? 'bg-green-50 text-green-700'
                            : field.source === 'environment'
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {field.source === 'stored'
                          ? 'Stored'
                          : field.source === 'environment'
                            ? 'Env fallback'
                            : 'Default'}
                      </span>
                    </div>

                    <div className="mt-4 space-y-3">
                      {field.input_type === 'select' ? (
                        <select
                          className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                          id={field.key}
                          onChange={(event) => handleFieldChange(field.key, event.target.value)}
                          value={draftValues[field.key] || ''}
                        >
                          {(field.options || []).map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          className="block w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm text-gray-900 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                          id={field.key}
                          onChange={(event) => handleFieldChange(field.key, event.target.value)}
                          placeholder={
                            field.secret
                              ? field.masked_value || 'Not configured'
                              : field.description
                          }
                          type={field.input_type === 'password' ? 'password' : 'text'}
                          value={draftValues[field.key] || ''}
                        />
                      )}

                      {field.secret && (
                        <div className="rounded-xl bg-gray-50 p-3">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <span className="min-w-0 break-all text-sm text-gray-600">
                              {configuredSecret
                                ? `Stored value: ${formatMaskedValue(field.masked_value)}`
                                : clearedKeys[field.key]
                                  ? 'This secret will be cleared on save.'
                                  : 'Leave blank to keep the current secret unchanged.'}
                            </span>
                          {field.configured && (
                            <button
                              className="shrink-0 text-left text-sm font-medium text-red-600 hover:text-red-500"
                              onClick={() => handleClearSecret(field.key)}
                              type="button"
                            >
                              Clear saved value
                            </button>
                          )}
                          </div>
                        </div>
                      )}

                      {field.updated_at && (
                        <div className="flex items-center gap-2 break-words text-xs text-gray-400">
                          <CheckCircleIcon className="h-4 w-4" />
                          Updated {new Date(field.updated_at).toLocaleString()}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
