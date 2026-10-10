import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  ExternalLink,
  Info,
  KeyRound,
  Loader2,
  RefreshCw,
  RotateCw,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import { api, apiData, ApiError, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type LLMProvider = components['schemas']['LLMProvider'];
type LLMProtocol = components['schemas']['LLMProtocol'];
type LLMCredentialSource = components['schemas']['LLMCredentialSource'];
type LLMCatalogStatus = components['schemas']['LLMCatalogStatus'];
type LLMProviderResponse = components['schemas']['LLMProviderResponse'];
type LLMRouteResponse = components['schemas']['LLMRouteResponse'];
type LLMCatalogTestResponse = components['schemas']['LLMCatalogTestResponse'];

const PROVIDER_ORDER: LLMProvider[] = [
  'OPENAI',
  'ANTHROPIC',
  'GEMINI',
  'DEEPSEEK',
  'OPENCODE_ZEN',
  'BEDROCK',
];

const BLOCKER_LABELS: Record<string, string> = {
  provider_disabled: 'Selected provider is disabled',
  credential_not_verified: 'Credential is not configured or modified since verification',
  data_policy_not_approved: 'Provider data policy / zero-retention terms are not approved',
  catalog_not_verified: 'Provider catalog access has not been verified for current credential revision',
  max_tokens_invalid: 'Max tokens must be between 1 and 1024',
  quality_not_approved: 'Quality gate operational approval is required',
  model_missing: 'Model ID is required',
  protocol_not_supported: 'Selected protocol is not supported by provider',
  region_missing: 'AWS region is required for Amazon Bedrock',
  geographic_profile_not_approved: 'Bedrock model and geographic profile are not approved',
};

function humanBlocker(blocker: string): string {
  return BLOCKER_LABELS[blocker] ?? blocker.replace(/_/g, ' ');
}

const CATALOG_STATUS_CONFIG: Record<
  LLMCatalogStatus,
  { label: string; bg: string; text: string; border: string; icon: React.FC<{ className?: string }> }
> = {
  CATALOG_VERIFIED: {
    label: 'Catalog verified',
    bg: 'bg-emerald-50',
    text: 'text-emerald-700',
    border: 'border-emerald-200',
    icon: CheckCircle2,
  },
  UNTESTED: {
    label: 'Untested',
    bg: 'bg-slate-50',
    text: 'text-slate-600',
    border: 'border-slate-200',
    icon: Info,
  },
  INVALID_CREDENTIAL: {
    label: 'Invalid credential',
    bg: 'bg-rose-50',
    text: 'text-rose-700',
    border: 'border-rose-200',
    icon: AlertCircle,
  },
  RATE_LIMITED: {
    label: 'Rate limited',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    border: 'border-amber-200',
    icon: AlertTriangle,
  },
  UNAVAILABLE: {
    label: 'Unavailable',
    bg: 'bg-rose-50',
    text: 'text-rose-700',
    border: 'border-rose-200',
    icon: AlertCircle,
  },
  TIMEOUT: {
    label: 'Timeout',
    bg: 'bg-amber-50',
    text: 'text-amber-700',
    border: 'border-amber-200',
    icon: AlertTriangle,
  },
  INVALID_RESPONSE: {
    label: 'Invalid response',
    bg: 'bg-rose-50',
    text: 'text-rose-700',
    border: 'border-rose-200',
    icon: AlertCircle,
  },
};

const PROTOCOL_LABELS: Record<LLMProtocol, string> = {
  OPENAI_CHAT: 'OpenAI Chat (/v1/chat/completions)',
  OPENAI_RESPONSES: 'OpenAI Responses (/v1/responses)',
  ANTHROPIC_MESSAGES: 'Anthropic Messages (/v1/messages)',
  GEMINI_GENERATE_CONTENT: 'Google Gemini (generateContent)',
  BEDROCK_CONVERSE: 'Amazon Bedrock (Converse API)',
};

const inputClass =
  'block w-full px-3 py-2 text-sm bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#1F4B7A]/20 focus:border-[#1F4B7A] disabled:bg-slate-50 disabled:text-slate-500';

// ----------------------------------------------------------------------
// Configure Provider Dialog
// ----------------------------------------------------------------------
interface ConfigureProviderModalProps {
  provider: LLMProviderResponse;
  onClose: () => void;
  onSuccess: () => void;
}

const ConfigureProviderModal: React.FC<ConfigureProviderModalProps> = ({
  provider,
  onClose,
  onSuccess,
}) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const passwordInputRef = useRef<HTMLInputElement>(null);

  const [credentialSource, setCredentialSource] = useState<LLMCredentialSource>(
    provider.provider === 'BEDROCK' ? 'NONE' : provider.credential_source,
  );
  const [environmentKeyName, setEnvironmentKeyName] = useState<string>(
    provider.environment_key_name ?? provider.supported_environment_keys[0] ?? '',
  );
  const [credentialKey, setCredentialKey] = useState<string>('');
  const [enabled, setEnabled] = useState<boolean>(provider.enabled);
  const [dataPolicyApproved, setDataPolicyApproved] = useState<boolean>(
    provider.data_policy_approved,
  );
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setSaving(true);
    try {
      const isBedrock = provider.provider === 'BEDROCK';
      const bodySource: LLMCredentialSource = isBedrock ? 'NONE' : credentialSource;

      await apiData(
        api.PUT('/api/v1/operations/llm/providers/{provider}', {
          params: {
            path: { provider: provider.provider },
            header: { 'If-Match': `"rev-${provider.revision}"` },
          },
          body: {
            enabled,
            credential_source: bodySource,
            environment_key_name:
              bodySource === 'ENVIRONMENT' ? environmentKeyName || null : null,
            credential_key:
              bodySource === 'STORED' && credentialKey.trim().length > 0
                ? credentialKey.trim()
                : null,
            data_policy_approved: dataPolicyApproved,
          },
        }),
      );

      // Clean password
      setCredentialKey('');
      if (passwordInputRef.current) passwordInputRef.current.value = '';

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
      onSuccess();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setError(
          'Provider settings were modified concurrently (revision conflict). Please close and reload.',
        );
      } else {
        setError(getErrorMessage(err));
      }
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveCredential = async () => {
    setError(undefined);
    setRemoving(true);
    try {
      await apiData(
        api.DELETE('/api/v1/operations/llm/providers/{provider}/credential', {
          params: {
            path: { provider: provider.provider },
            header: { 'If-Match': `"rev-${provider.revision}"` },
          },
        }),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
      onSuccess();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setError('Revision mismatch. Please close and reload provider state.');
      } else {
        setError(getErrorMessage(err));
      }
    } finally {
      setRemoving(false);
      setShowRemoveConfirm(false);
    }
  };

  const isBedrock = provider.provider === 'BEDROCK';
  const canRemove =
    !isBedrock && provider.credential_source !== 'NONE';

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="configure-modal-title"
      onCancel={(e) => {
        if (saving || removing) e.preventDefault();
      }}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-xl border border-slate-200 p-6 bg-white shadow-2xl backdrop:bg-slate-900/50"
    >
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <KeyRound className="w-5 h-5 text-[#1F4B7A]" />
          <h2 id="configure-modal-title" className="font-bold text-lg text-slate-900">
            Configure {provider.display_name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={saving || removing}
          className="text-slate-400 hover:text-slate-600 rounded p-1 hover:bg-slate-100 disabled:opacity-50"
          aria-label="Close dialog"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-700 flex items-start gap-2"
        >
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{error}</div>
        </div>
      )}

      {showRemoveConfirm ? (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl space-y-3 mb-4">
          <div className="flex items-center gap-2 text-rose-800 font-semibold text-sm">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
            <span>Confirm Credential Removal</span>
          </div>
          <p className="text-xs text-rose-700 leading-relaxed">
            Removing the credential for <strong>{provider.display_name}</strong> will delete any
            stored key. If an active route uses this provider, it will be automatically
            deactivated.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              disabled={removing}
              onClick={() => setShowRemoveConfirm(false)}
              className="px-3 py-1.5 text-xs font-medium border border-slate-300 rounded-lg bg-white hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={removing}
              onClick={handleRemoveCredential}
              className="px-3 py-1.5 text-xs font-medium bg-rose-600 text-white rounded-lg hover:bg-rose-700 disabled:opacity-50 flex items-center gap-1.5"
            >
              {removing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {removing ? 'Removing...' : 'Yes, remove credential'}
            </button>
          </div>
        </div>
      ) : null}

      <form onSubmit={handleSave} className="space-y-4">
        <fieldset disabled={saving || removing} className="space-y-4">
          {/* Provider status details */}
          <div className="flex items-center justify-between text-xs text-slate-500 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
            <span>
              Current Revision: <strong className="text-slate-700">rev-{provider.revision}</strong>
            </span>
            <a
              href={provider.docs_url}
              target="_blank"
              rel="noreferrer"
              className="text-[#1F4B7A] hover:underline flex items-center gap-1"
            >
              Official Documentation <ExternalLink className="w-3 h-3" />
            </a>
          </div>

          {/* Credential Source Selection */}
          <div>
            <label className="block text-sm font-semibold text-slate-900 mb-1.5">
              Credential Source
            </label>
            {isBedrock ? (
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900 leading-relaxed">
                <p className="font-semibold mb-1">AWS IAM Credential Chain</p>
                Amazon Bedrock authenticates via the server runtime AWS IAM role / environment
                credentials. No API key input or storage is required.
              </div>
            ) : (
              <div className="space-y-2">
                <label className="flex items-center gap-2.5 p-2.5 border border-slate-200 rounded-lg hover:bg-slate-50 cursor-pointer text-sm">
                  <input
                    type="radio"
                    name="credential_source"
                    value="ENVIRONMENT"
                    checked={credentialSource === 'ENVIRONMENT'}
                    onChange={() => setCredentialSource('ENVIRONMENT')}
                    className="text-[#1F4B7A] focus:ring-[#1F4B7A]"
                  />
                  <div>
                    <span className="font-medium text-slate-800">Server environment variable</span>
                    <p className="text-xs text-slate-500">
                      Read API key from pre-configured server environment
                    </p>
                  </div>
                </label>

                <label
                  className={`flex items-center gap-2.5 p-2.5 border border-slate-200 rounded-lg text-sm ${
                    provider.stored_credentials_available
                      ? 'hover:bg-slate-50 cursor-pointer'
                      : 'bg-slate-50 text-slate-500 cursor-not-allowed'
                  }`}
                >
                  <input
                    type="radio"
                    name="credential_source"
                    value="STORED"
                    checked={credentialSource === 'STORED'}
                    disabled={!provider.stored_credentials_available}
                    onChange={() => setCredentialSource('STORED')}
                    className="text-[#1F4B7A] focus:ring-[#1F4B7A]"
                  />
                  <div>
                    <span className="font-medium text-slate-800">Encrypted database storage</span>
                    <p className="text-xs text-slate-500">
                      {provider.stored_credentials_available
                        ? 'Paste key; authenticated encryption keyring applies in database'
                        : 'Unavailable until server LLM credential keyring is configured'}
                    </p>
                  </div>
                </label>

                <label className="flex items-center gap-2.5 p-2.5 border border-slate-200 rounded-lg hover:bg-slate-50 cursor-pointer text-sm">
                  <input
                    type="radio"
                    name="credential_source"
                    value="NONE"
                    checked={credentialSource === 'NONE'}
                    onChange={() => setCredentialSource('NONE')}
                    className="text-[#1F4B7A] focus:ring-[#1F4B7A]"
                  />
                  <div>
                    <span className="font-medium text-slate-800">Not configured</span>
                    <p className="text-xs text-slate-500">No active credentials for this provider</p>
                  </div>
                </label>
              </div>
            )}
          </div>

          {/* Conditional Credential Inputs */}
          {!isBedrock && credentialSource === 'ENVIRONMENT' && (
            <div>
              <label
                htmlFor="env-key-select"
                className="block text-sm font-medium text-slate-800 mb-1"
              >
                Environment Variable Name
              </label>
              <select
                id="env-key-select"
                value={environmentKeyName}
                onChange={(e) => setEnvironmentKeyName(e.target.value)}
                className={inputClass}
                required
              >
                {provider.supported_environment_keys.map((key) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>
              <p className="text-xs text-slate-500 mt-1">
                Must be present in the API and worker server environment allowlist.
              </p>
            </div>
          )}

          {!isBedrock && credentialSource === 'STORED' && (
            <div>
              <label
                htmlFor="stored-key-input"
                className="block text-sm font-medium text-slate-800 mb-1"
              >
                API Key (Encrypted Storage)
              </label>
              <input
                id="stored-key-input"
                ref={passwordInputRef}
                type="password"
                autoComplete="new-password"
                value={credentialKey}
                onChange={(e) => setCredentialKey(e.target.value)}
                placeholder={
                  provider.stored_credentials_available
                    ? `Current hint: ${provider.masked_hint ?? 'Configured'} (leave blank to keep)`
                    : 'Paste provider API key...'
                }
                className={inputClass}
              />
              <p className="text-xs text-slate-500 mt-1">
                Stored using authenticated database encryption. Plaintext is never returned by API
                or written to application logs.
              </p>
            </div>
          )}

          {/* Enabled Toggle */}
          <div className="pt-1">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="w-4 h-4 rounded text-[#1F4B7A] focus:ring-[#1F4B7A] border-slate-300"
              />
              <span className="text-sm font-medium text-slate-800">
                Enable provider for Citation Semantic tasks
              </span>
            </label>
          </div>

          {/* Data Policy Approval Checkbox */}
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={dataPolicyApproved}
                onChange={(e) => setDataPolicyApproved(e.target.checked)}
                className="w-4 h-4 mt-0.5 rounded text-[#1F4B7A] focus:ring-[#1F4B7A] border-slate-300 shrink-0"
              />
              <div className="text-xs text-slate-700 leading-relaxed">
                <span className="font-semibold text-slate-900 block">
                  Data Policy & Privacy Attestation
                </span>
                I confirm that I have verified the provider&apos;s terms and privacy policies,
                confirming zero-retention or acceptable data handling and that prompt data is not
                used for model training.
              </div>
            </label>
          </div>
        </fieldset>

        {/* Dialog Actions */}
        <div className="flex items-center justify-between pt-3 border-t border-slate-200">
          <div>
            {canRemove && !showRemoveConfirm && (
              <button
                type="button"
                disabled={saving || removing}
                onClick={() => setShowRemoveConfirm(true)}
                className="text-xs font-medium text-rose-600 hover:text-rose-800 flex items-center gap-1 py-1.5 px-2 rounded hover:bg-rose-50 disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" /> Remove credential
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={saving || removing}
              onClick={onClose}
              className="px-3.5 py-2 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || removing}
              className="px-4 py-2 text-sm font-medium bg-[#1F4B7A] text-white rounded-lg hover:bg-[#183B61] disabled:opacity-50 flex items-center gap-1.5"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              {saving ? 'Saving...' : 'Save Configuration'}
            </button>
          </div>
        </div>
      </form>
    </dialog>
  );
};

// ----------------------------------------------------------------------
// Route Activation Confirmation Modal
// ----------------------------------------------------------------------
interface ActivationModalProps {
  route: LLMRouteResponse;
  providerName: string;
  onClose: () => void;
  onSuccess: () => void;
}

const RouteActivationModal: React.FC<ActivationModalProps> = ({
  route,
  providerName,
  onClose,
  onSuccess,
}) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string>();
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleActivate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!acknowledged) return;
    setError(undefined);
    setActivating(true);
    try {
      await apiData(
        api.POST('/api/v1/operations/llm/routes/CITATION_SEMANTIC/activate', {
          params: {
            header: { 'If-Match': `"rev-${route.revision}"` },
          },
          body: {
            acknowledge_provider_fees: true,
          },
        }),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
      onSuccess();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setError(
          'Route revision changed concurrently. Please close, reload the route, and try again.',
        );
      } else {
        setError(getErrorMessage(err));
      }
    } finally {
      setActivating(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="activation-modal-title"
      onCancel={(e) => {
        if (activating) e.preventDefault();
      }}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-xl border border-slate-200 p-6 bg-white shadow-2xl backdrop:bg-slate-900/50"
    >
      <div className="flex items-center justify-between border-b border-slate-200 pb-3 mb-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-amber-600" />
          <h2 id="activation-modal-title" className="font-bold text-lg text-slate-900">
            Activate Citation Semantic Route
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={activating}
          className="text-slate-400 hover:text-slate-600 rounded p-1 hover:bg-slate-100 disabled:opacity-50"
          aria-label="Close dialog"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 p-3 bg-rose-50 border border-rose-200 rounded-lg text-sm text-rose-700 flex items-start gap-2"
        >
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>{error}</div>
        </div>
      )}

      <form onSubmit={handleActivate} className="space-y-4">
        {/* Route Snapshot Summary */}
        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-1.5">
          <div className="flex justify-between">
            <span className="text-slate-500">Provider:</span>
            <span className="font-semibold text-slate-800">{providerName}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Model ID:</span>
            <span className="font-mono text-slate-800">{route.model_id || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Protocol:</span>
            <span className="text-slate-800">{route.protocol}</span>
          </div>
          {route.region && (
            <div className="flex justify-between">
              <span className="text-slate-500">Region:</span>
              <span className="text-slate-800">{route.region}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-slate-500">Max tokens per call:</span>
            <span className="text-slate-800">{route.max_tokens}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Call budget per job:</span>
            <span className="text-slate-800">{route.call_budget}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Job attempts:</span>
            <span className="text-slate-800">Up to 3 durable attempts</span>
          </div>
        </div>

        {/* Warning Callout */}
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 space-y-2 leading-relaxed">
          <p className="font-semibold flex items-center gap-1.5 text-amber-800">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
            External Quota & Fee Warning
          </p>
          <p>
            Student-submitted analysis requests will trigger live model generation calls against
            this provider account. Automated billing, chargeback, and token cost tracking are not
            implemented.
          </p>
          <p>
            There is <strong>no automatic failover</strong> to alternative providers. If the provider
            encounters outages, timeouts, or quota limits, the analysis job will fail closed and
            require manual grading review.
          </p>
        </div>

        {/* Acknowledgment Checkbox */}
        <div className="pt-2">
          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="w-4 h-4 mt-0.5 rounded text-[#1F4B7A] focus:ring-[#1F4B7A] border-slate-300 shrink-0"
              required
            />
            <span className="text-xs text-slate-800 font-medium leading-relaxed">
              I acknowledge provider fee/quota implications, durable attempt limits, and the lack of
              automatic failover.
            </span>
          </label>
        </div>

        {/* Modal Actions */}
        <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-200">
          <button
            type="button"
            disabled={activating}
            onClick={onClose}
            className="px-3.5 py-2 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!acknowledged || activating}
            className="px-4 py-2 text-sm font-medium bg-emerald-700 text-white rounded-lg hover:bg-emerald-800 disabled:opacity-50 flex items-center gap-1.5"
          >
            {activating && <Loader2 className="w-4 h-4 animate-spin" />}
            {activating ? 'Activating...' : 'Confirm & Activate Route'}
          </button>
        </div>
      </form>
    </dialog>
  );
};

// ----------------------------------------------------------------------
// Main LLMProviderSettingsView Component
// ----------------------------------------------------------------------
export const LLMProviderSettingsView: React.FC = () => {
  const queryClient = useQueryClient();

  // Queries
  const providersQuery = useQuery({
    queryKey: ['llm-providers'],
    queryFn: () => apiData(api.GET('/api/v1/operations/llm/providers')),
  });

  const routeQuery = useQuery({
    queryKey: ['llm-route'],
    queryFn: () => apiData(api.GET('/api/v1/operations/llm/routes/CITATION_SEMANTIC')),
  });

  // State
  const [editingProvider, setEditingProvider] = useState<LLMProviderResponse | null>(null);
  const [activatingRoute, setActivatingRoute] = useState<LLMRouteResponse | null>(null);
  const [testedCatalogModels, setTestedCatalogModels] = useState<{
    provider: LLMProvider;
    models: string[];
  } | null>(null);
  const [testPendingProvider, setTestPendingProvider] = useState<LLMProvider | null>(null);
  const [testResultFeedback, setTestResultFeedback] = useState<{
    provider: LLMProvider;
    status: LLMCatalogStatus;
    latencyMs: number | null;
    error?: string;
  } | null>(null);

  // Route Form State
  const [selectedProvider, setSelectedProvider] = useState<LLMProvider>('OPENAI');
  const [modelId, setModelId] = useState<string>('');
  const [protocol, setProtocol] = useState<LLMProtocol>('OPENAI_CHAT');
  const [region, setRegion] = useState<string>('');
  const [geographicProfile, setGeographicProfile] = useState<string>('');
  const [maxTokens, setMaxTokens] = useState<number>(512);
  const [callBudget, setCallBudget] = useState<number>(32);
  const [qualityApproved, setQualityApproved] = useState<boolean>(false);
  const [routeFormInitialized, setRouteFormInitialized] = useState(false);
  const [hydratedRevision, setHydratedRevision] = useState<number | null>(null);

  const [routeSaveError, setRouteSaveError] = useState<string>();
  const [routeSaveSuccess, setRouteSaveSuccess] = useState(false);
  const [routeSaving, setRouteSaving] = useState(false);
  const [deactivatingRoute, setDeactivatingRoute] = useState(false);
  const [deactivateError, setDeactivateError] = useState<string>();

  // Synchronize route form when data loads
  useEffect(() => {
    if (routeQuery.data && !routeFormInitialized) {
      setSelectedProvider(routeQuery.data.provider);
      setModelId(routeQuery.data.model_id ?? '');
      setProtocol(routeQuery.data.protocol);
      setRegion(routeQuery.data.region ?? '');
      setGeographicProfile(routeQuery.data.geographic_profile ?? '');
      setMaxTokens(routeQuery.data.max_tokens);
      setCallBudget(routeQuery.data.call_budget);
      setQualityApproved(routeQuery.data.quality_approved);
      setHydratedRevision(routeQuery.data.revision);
      setRouteFormInitialized(true);
    }
  }, [routeQuery.data, routeFormInitialized]);

  // Provider lookup record
  const providersByCode = React.useMemo(() => {
    const lookup: Partial<Record<LLMProvider, LLMProviderResponse>> = {};
    providersQuery.data?.items.forEach((p) => {
      lookup[p.provider] = p;
    });
    return lookup;
  }, [providersQuery.data]);

  // When selected provider in route changes, ensure valid protocol
  const selectedProviderData = providersByCode[selectedProvider];
  useEffect(() => {
    if (selectedProviderData && selectedProviderData.supported_protocols.length > 0) {
      if (!selectedProviderData.supported_protocols.includes(protocol)) {
        setProtocol(selectedProviderData.supported_protocols[0]);
      }
    }
  }, [selectedProvider, selectedProviderData, protocol]);

  // Handle Catalog Test Mutation
  const handleTestCatalog = async (provider: LLMProviderResponse) => {
    setTestPendingProvider(provider.provider);
    setTestResultFeedback(null);
    try {
      const response: LLMCatalogTestResponse = await apiData(
        api.POST('/api/v1/operations/llm/providers/{provider}/test', {
          params: {
            path: { provider: provider.provider },
            header: { 'If-Match': `"rev-${provider.revision}"` },
          },
        }),
      );

      setTestResultFeedback({
        provider: provider.provider,
        status: response.status,
        latencyMs: response.latency_ms,
      });

      if (response.model_ids && response.model_ids.length > 0) {
        setTestedCatalogModels({
          provider: provider.provider,
          models: response.model_ids,
        });
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
      ]);
    } catch (err) {
      setTestResultFeedback({
        provider: provider.provider,
        status: 'INVALID_RESPONSE',
        latencyMs: null,
        error: getErrorMessage(err),
      });
    } finally {
      setTestPendingProvider(null);
    }
  };

  // Handle Save Route Draft
  const handleSaveRouteDraft = async (e: React.FormEvent) => {
    e.preventDefault();
    const revision = hydratedRevision ?? routeQuery.data?.revision;
    if (revision === undefined || revision === null) return;

    setRouteSaveError(undefined);
    setRouteSaveSuccess(false);
    setRouteSaving(true);

    try {
      const savedRoute = await apiData(
        api.PUT('/api/v1/operations/llm/routes/CITATION_SEMANTIC', {
          params: {
            header: { 'If-Match': `"rev-${revision}"` },
          },
          body: {
            provider: selectedProvider,
            model_id: modelId.trim() || null,
            protocol,
            region: selectedProvider === 'BEDROCK' ? region.trim() || null : null,
            geographic_profile:
              selectedProvider === 'BEDROCK' ? geographicProfile.trim() || null : null,
            max_tokens: Number(maxTokens),
            call_budget: Number(callBudget),
            quality_approved: qualityApproved,
          },
        }),
      );
      setHydratedRevision(savedRoute.revision);

      setRouteSaveSuccess(true);
      setTimeout(() => setRouteSaveSuccess(false), 4000);

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) {
        setRouteSaveError(
          'Route was modified by another session (revision conflict). Click "Reload Route" to load latest settings.',
        );
      } else {
        setRouteSaveError(getErrorMessage(err));
      }
    } finally {
      setRouteSaving(false);
    }
  };

  // Handle Deactivate Route
  const handleDeactivateRoute = async () => {
    if (!routeQuery.data) return;
    setDeactivateError(undefined);
    setDeactivatingRoute(true);
    try {
      await apiData(
        api.POST('/api/v1/operations/llm/routes/CITATION_SEMANTIC/deactivate', {
          params: {
            header: { 'If-Match': `"rev-${routeQuery.data.revision}"` },
          },
        }),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['llm-route'] }),
        queryClient.invalidateQueries({ queryKey: ['llm-providers'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
    } catch (err) {
      setDeactivateError(getErrorMessage(err));
    } finally {
      setDeactivatingRoute(false);
    }
  };

  const handleReloadRoute = async () => {
    setRouteSaveError(undefined);
    setDeactivateError(undefined);
    const refreshed = await routeQuery.refetch();
    if (refreshed.data) {
      setSelectedProvider(refreshed.data.provider);
      setModelId(refreshed.data.model_id ?? '');
      setProtocol(refreshed.data.protocol);
      setRegion(refreshed.data.region ?? '');
      setGeographicProfile(refreshed.data.geographic_profile ?? '');
      setMaxTokens(refreshed.data.max_tokens);
      setCallBudget(refreshed.data.call_budget);
      setQualityApproved(refreshed.data.quality_approved);
      setHydratedRevision(refreshed.data.revision);
    }
  };

  // Loading State
  const isLoading = providersQuery.isLoading || routeQuery.isLoading;
  const isError = providersQuery.isError || routeQuery.isError;
  const queryError = providersQuery.error || routeQuery.error;

  const currentRoute = routeQuery.data;
  const currentRouteProvider = currentRoute ? providersByCode[currentRoute.provider] : undefined;

  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#1F4B7A] text-white flex items-center justify-center">
              <Cpu className="w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900">AI providers</h1>
          </div>
          <p className="text-sm text-slate-600 mt-1">
            Manage centralized LLM provider credentials, catalog verification, and Citation
            Semantic routing.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={providersQuery.isFetching || routeQuery.isFetching}
            onClick={() => {
              void providersQuery.refetch();
              void routeQuery.refetch();
            }}
            className="px-3.5 py-2 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 flex items-center gap-1.5 text-slate-700 disabled:opacity-50"
          >
            <RefreshCw
              className={`w-4 h-4 ${
                providersQuery.isFetching || routeQuery.isFetching ? 'animate-spin' : ''
              }`}
            />
            Refresh
          </button>
        </div>
      </div>

      {/* Query Error State */}
      {isError && (
        <div
          role="alert"
          className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 flex items-start gap-3"
        >
          <AlertCircle className="w-5 h-5 mt-0.5 shrink-0 text-rose-600" />
          <div className="flex-1">
            <h3 className="font-semibold text-sm">Failed to load LLM settings</h3>
            <p className="text-xs text-rose-700 mt-1">{getErrorMessage(queryError)}</p>
            <button
              type="button"
              onClick={() => {
                void providersQuery.refetch();
                void routeQuery.refetch();
              }}
              className="mt-3 px-3 py-1.5 text-xs font-medium bg-rose-600 text-white rounded-lg hover:bg-rose-700"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-4" role="status" aria-label="Loading provider settings">
          <div className="h-28 bg-slate-200 animate-pulse rounded-xl" />
          <div className="h-48 bg-slate-200 animate-pulse rounded-xl" />
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="h-44 bg-slate-200 animate-pulse rounded-xl" />
            ))}
          </div>
        </div>
      )}

      {!isLoading && !isError && currentRoute && (
        <>
          {/* Permanent Amber Cost & Usage Disclosure */}
          <section
            aria-label="Cost and usage disclosure"
            className="p-4 sm:p-5 bg-amber-50 border border-amber-200 text-amber-950 rounded-xl flex items-start gap-3.5 shadow-sm"
          >
            <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" />
            <div className="space-y-2 text-xs leading-relaxed flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-bold text-sm text-amber-900">
                  External Provider Usage &amp; Cost Disclosure
                </h2>
                <span className="px-2 py-0.5 bg-amber-200/80 text-amber-900 rounded font-semibold text-[11px]">
                  Billing / Chargeback Not Implemented
                </span>
              </div>
              <p>
                Student-triggered analysis jobs consume external LLM provider quota and may incur
                direct provider charges. DocGrading does not estimate costs, calculate charges, or
                provide automated cost limits.
              </p>
              <div className="flex flex-wrap items-center gap-2 pt-1 font-mono text-[11px]">
                <span className="bg-amber-100 text-amber-900 px-2 py-1 rounded border border-amber-200">
                  Max tokens/call: {currentRoute.max_tokens}
                </span>
                <span className="bg-amber-100 text-amber-900 px-2 py-1 rounded border border-amber-200">
                  Call budget/job: {currentRoute.call_budget}
                </span>
                <span className="bg-amber-100 text-amber-900 px-2 py-1 rounded border border-amber-200">
                  Durable attempts: Up to 3
                </span>
                <span className="bg-amber-100 text-amber-900 px-2 py-1 rounded border border-amber-200">
                  Failover: Manual review only
                </span>
              </div>
            </div>
          </section>

          {/* Route Summary Section */}
          <section
            aria-label="Citation semantic route status"
            className="p-5 sm:p-6 bg-white border border-slate-200 rounded-xl shadow-sm space-y-4"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <h2 className="font-bold text-lg text-slate-900">Citation Semantic Route</h2>
                  {currentRoute.state === 'ACTIVE' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Active
                    </span>
                  ) : currentRoute.state === 'DRAFT' ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                      <Info className="w-3.5 h-3.5" /> Draft
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                      <ShieldAlert className="w-3.5 h-3.5" /> Manual review only
                    </span>
                  )}
                  <span className="text-xs text-slate-400">rev-{currentRoute.revision}</span>
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Task identifier:{' '}
                  <code className="font-mono text-slate-700">CITATION_SEMANTIC</code> · Single
                  versioned route for automated citation grounding.
                </p>
              </div>

              {/* Route Lifecycle Action Buttons */}
              <div className="flex items-center gap-2">
                {currentRoute.state === 'ACTIVE' ? (
                  <button
                    type="button"
                    disabled={deactivatingRoute}
                    onClick={handleDeactivateRoute}
                    className="px-3.5 py-2 text-xs font-semibold text-rose-700 bg-rose-50 border border-rose-200 rounded-lg hover:bg-rose-100 disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {deactivatingRoute && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    {deactivatingRoute ? 'Deactivating...' : 'Deactivate Route'}
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={!currentRoute.ready}
                    onClick={() => setActivatingRoute(currentRoute)}
                    title={
                      currentRoute.ready
                        ? 'Activate this route'
                        : 'Prerequisites unresolved. Check blocker list.'
                    }
                    className="px-4 py-2 text-xs font-semibold text-white bg-emerald-700 rounded-lg hover:bg-emerald-800 disabled:bg-slate-200 disabled:text-slate-400 disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" /> Activate Route
                  </button>
                )}
              </div>
            </div>

            {deactivateError && (
              <div
                role="alert"
                className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700 flex items-start gap-2"
              >
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <div>{deactivateError}</div>
              </div>
            )}

            {/* Route Status Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                <span className="text-slate-500 block">Target Provider</span>
                <span className="font-semibold text-slate-800 text-sm mt-0.5 block">
                  {currentRouteProvider?.display_name ?? currentRoute.provider}
                </span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                <span className="text-slate-500 block">Configured Model</span>
                <span className="font-mono font-medium text-slate-800 text-sm mt-0.5 block truncate">
                  {currentRoute.model_id || '(No model set)'}
                </span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                <span className="text-slate-500 block">Protocol</span>
                <span className="font-medium text-slate-800 text-xs mt-0.5 block truncate">
                  {currentRoute.protocol}
                </span>
              </div>
              <div className="p-3 bg-slate-50 rounded-lg border border-slate-100">
                <span className="text-slate-500 block">Limits &amp; Quality</span>
                <span className="font-medium text-slate-800 text-xs mt-0.5 block">
                  {currentRoute.max_tokens} tok · {currentRoute.call_budget} calls ·{' '}
                  {currentRoute.quality_approved ? 'Approved' : 'Unapproved'}
                </span>
              </div>
            </div>

            {/* Readiness & Blockers */}
            <div className="pt-2">
              {currentRoute.ready ? (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center justify-between text-xs text-emerald-800">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                    <span>
                      <strong>Prerequisites satisfied.</strong> Provider credential verified, data
                      policy approved, and quality gate attested. Ready for activation.
                    </span>
                  </div>
                </div>
              ) : (
                <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-950 space-y-2">
                  <div className="flex items-center gap-2 font-semibold text-amber-900">
                    <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                    <span>Activation Blockers ({currentRoute.blockers.length}):</span>
                  </div>
                  <ul className="list-disc list-inside space-y-1 pl-1 text-amber-800">
                    {currentRoute.blockers.map((b) => (
                      <li key={b}>
                        <strong>{humanBlocker(b)}</strong>{' '}
                        <span className="font-mono text-[10px] text-amber-700">({b})</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-[11px] text-slate-500 pt-1 border-t border-amber-200/60">
                    Note: <em>Ready</em> reflects operational prerequisites only. Catalog verification
                    confirms credential connectivity, not generation accuracy or model health.
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* Route Configuration Editor */}
          <section
            aria-label="Edit citation semantic route"
            className="p-5 sm:p-6 bg-white border border-slate-200 rounded-xl shadow-sm space-y-5"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
              <div>
                <h2 className="font-bold text-base text-slate-900">Route Configuration Editor</h2>
                <p className="text-xs text-slate-500">
                  Update model parameters. Saving will place the route into <strong>DRAFT</strong>{' '}
                  state.
                </p>
              </div>
              {routeSaveError && (
                <button
                  type="button"
                  onClick={handleReloadRoute}
                  className="text-xs text-[#1F4B7A] font-semibold hover:underline flex items-center gap-1"
                >
                  <RotateCw className="w-3.5 h-3.5" /> Reload Route
                </button>
              )}
            </div>

            {routeSaveError && (
              <div
                role="alert"
                className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700 flex items-start gap-2"
              >
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  <p>{routeSaveError}</p>
                </div>
              </div>
            )}

            {routeSaveSuccess && (
              <div
                role="status"
                className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>Route configuration saved as Draft successfully.</span>
              </div>
            )}

            <form onSubmit={handleSaveRouteDraft} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {/* Provider Select */}
                <div>
                  <label
                    htmlFor="route-provider-select"
                    className="block text-xs font-semibold text-slate-800 mb-1"
                  >
                    LLM Provider
                  </label>
                  <select
                    id="route-provider-select"
                    value={selectedProvider}
                    onChange={(e) => setSelectedProvider(e.target.value as LLMProvider)}
                    className={inputClass}
                  >
                    {PROVIDER_ORDER.map((prov) => {
                      const p = providersByCode[prov];
                      return (
                        <option key={prov} value={prov}>
                          {p?.display_name ?? prov} {!p?.configured ? '(Not configured)' : ''}
                        </option>
                      );
                    })}
                  </select>
                </div>

                {/* Model ID */}
                <div>
                  <label
                    htmlFor="route-model-input"
                    className="block text-xs font-semibold text-slate-800 mb-1"
                  >
                    Model ID
                  </label>
                  <input
                    id="route-model-input"
                    type="text"
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                    placeholder="e.g. gpt-4o-mini, claude-3-5-sonnet-20241022..."
                    className={inputClass}
                    required
                  />
                  {testedCatalogModels && testedCatalogModels.provider === selectedProvider && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1">
                      <span className="text-[10px] text-slate-500">Catalog suggestions:</span>
                      {testedCatalogModels.models.slice(0, 5).map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => setModelId(m)}
                          className="px-1.5 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded text-[10px] font-mono"
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Protocol Select */}
                <div>
                  <label
                    htmlFor="route-protocol-select"
                    className="block text-xs font-semibold text-slate-800 mb-1"
                  >
                    Protocol
                  </label>
                  <select
                    id="route-protocol-select"
                    value={protocol}
                    onChange={(e) => setProtocol(e.target.value as LLMProtocol)}
                    className={inputClass}
                  >
                    {(
                      selectedProviderData?.supported_protocols ?? [
                        'OPENAI_CHAT',
                        'OPENAI_RESPONSES',
                        'ANTHROPIC_MESSAGES',
                        'GEMINI_GENERATE_CONTENT',
                        'BEDROCK_CONVERSE',
                      ]
                    ).map((prot) => (
                      <option key={prot} value={prot}>
                        {PROTOCOL_LABELS[prot] ?? prot}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Bedrock-only Region & Geo Profile */}
                {selectedProvider === 'BEDROCK' && (
                  <>
                    <div>
                      <label
                        htmlFor="route-region-input"
                        className="block text-xs font-semibold text-slate-800 mb-1"
                      >
                        AWS Region (Bedrock)
                      </label>
                      <input
                        id="route-region-input"
                        type="text"
                        value={region}
                        onChange={(e) => setRegion(e.target.value)}
                        placeholder="e.g. us-east-1, us-west-2"
                        className={inputClass}
                        required={selectedProvider === 'BEDROCK'}
                      />
                    </div>

                    <div>
                      <label
                        htmlFor="route-geo-profile-input"
                        className="block text-xs font-semibold text-slate-800 mb-1"
                      >
                        Geographic Profile (Bedrock)
                      </label>
                      <input
                        id="route-geo-profile-input"
                        type="text"
                        value={geographicProfile}
                        onChange={(e) => setGeographicProfile(e.target.value)}
                        placeholder="e.g. us. or leave blank"
                        className={inputClass}
                      />
                      <p className="text-[10px] text-slate-500 mt-0.5">
                        Required if model ID uses prefix (e.g. us.anthropic.claude-3-5-sonnet)
                      </p>
                    </div>
                  </>
                )}

                {/* Max Tokens */}
                <div>
                  <label
                    htmlFor="route-max-tokens-input"
                    className="block text-xs font-semibold text-slate-800 mb-1"
                  >
                    Max Tokens per Call (1–1024)
                  </label>
                  <input
                    id="route-max-tokens-input"
                    type="number"
                    min={1}
                    max={1024}
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(Number(e.target.value))}
                    className={inputClass}
                    required
                  />
                </div>

                {/* Call Budget */}
                <div>
                  <label
                    htmlFor="route-call-budget-input"
                    className="block text-xs font-semibold text-slate-800 mb-1"
                  >
                    Call Budget per Job (1–256)
                  </label>
                  <input
                    id="route-call-budget-input"
                    type="number"
                    min={1}
                    max={256}
                    value={callBudget}
                    onChange={(e) => setCallBudget(Number(e.target.value))}
                    className={inputClass}
                    required
                  />
                </div>
              </div>

              {/* Quality Approval Gate */}
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={qualityApproved}
                    onChange={(e) => setQualityApproved(e.target.checked)}
                    className="w-4 h-4 mt-0.5 rounded text-[#1F4B7A] focus:ring-[#1F4B7A] border-slate-300 shrink-0"
                  />
                  <div className="text-xs text-slate-700 leading-relaxed">
                    <span className="font-semibold text-slate-900 block">
                      Quality Gate Operational Approval
                    </span>
                    Operational attestation: I confirm that this model and parameter configuration has
                    been evaluated and approved for Citation Semantic task execution.
                    <span className="block text-slate-500 text-[11px] mt-0.5">
                      Note: Repository semantic auto-score remains separately blocked without
                      benchmark and domain sign-off.
                    </span>
                  </div>
                </label>
              </div>

              {/* Form Action */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
                <p className="text-xs text-slate-500">
                  Saving deactivates the route until explicitly activated with fee confirmation.
                </p>
                <button
                  type="submit"
                  disabled={routeSaving}
                  className="px-5 py-2 text-sm font-semibold bg-[#1F4B7A] text-white rounded-lg hover:bg-[#183B61] disabled:opacity-50 flex items-center justify-center gap-1.5 self-end"
                >
                  {routeSaving && <Loader2 className="w-4 h-4 animate-spin" />}
                  {routeSaving ? 'Saving Draft...' : 'Save Draft Configuration'}
                </button>
              </div>
            </form>
          </section>

          {/* Provider Inventory Section */}
          <section aria-label="Provider inventory" className="space-y-4">
            <div className="border-b border-slate-200 pb-3">
              <h2 className="font-bold text-lg text-slate-900">Provider Inventory</h2>
              <p className="text-xs text-slate-500">
                Credentials, data policies, and catalog connectivity for supported LLM providers.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {PROVIDER_ORDER.map((provKey) => {
                const provider = providersByCode[provKey];
                if (!provider) return null;

                const catalogStatusCfg =
                  CATALOG_STATUS_CONFIG[provider.catalog_status] ??
                  CATALOG_STATUS_CONFIG.UNTESTED;
                const StatusIcon = catalogStatusCfg.icon;
                const isTesting = testPendingProvider === provider.provider;
                const isTestedFeedback = testResultFeedback?.provider === provider.provider;

                return (
                  <div
                    key={provider.id || provider.provider}
                    className="p-5 bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col justify-between space-y-4"
                  >
                    <div>
                      {/* Provider Header */}
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div>
                          <h3 className="font-bold text-base text-slate-900">
                            {provider.display_name}
                          </h3>
                          <a
                            href={provider.docs_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[11px] text-[#1F4B7A] hover:underline flex items-center gap-1 mt-0.5"
                          >
                            Documentation <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                        <span className="text-[11px] font-mono text-slate-400">
                          rev-{provider.revision}
                        </span>
                      </div>

                      {/* Provider Status Badges */}
                      <div className="flex flex-wrap items-center gap-1.5 mb-3 text-[11px]">
                        {provider.configured ? (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                            Configured
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-slate-100 text-slate-600 border border-slate-200">
                            Not configured
                          </span>
                        )}

                        {provider.enabled ? (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-blue-50 text-blue-700 border border-blue-200">
                            Enabled
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-slate-100 text-slate-500 border border-slate-200">
                            Disabled
                          </span>
                        )}

                        {provider.data_policy_approved ? (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3" /> Policy approved
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full font-medium bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1">
                            <ShieldAlert className="w-3 h-3" /> Policy unapproved
                          </span>
                        )}
                      </div>

                      {/* Credential Source Details */}
                      <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-xs space-y-1 text-slate-700">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500">Source:</span>
                          <span className="font-medium text-slate-800">
                            {provider.provider === 'BEDROCK'
                              ? 'AWS IAM'
                              : provider.credential_source === 'ENVIRONMENT'
                              ? 'Server environment'
                              : provider.credential_source === 'STORED'
                              ? 'Encrypted storage'
                              : 'None'}
                          </span>
                        </div>
                        {provider.credential_source === 'ENVIRONMENT' &&
                          provider.environment_key_name && (
                            <div className="flex justify-between items-center font-mono text-[11px]">
                              <span className="text-slate-500">Key name:</span>
                              <span className="text-slate-800">{provider.environment_key_name}</span>
                            </div>
                          )}
                        {provider.credential_source === 'STORED' && (
                          <div className="flex justify-between items-center font-mono text-[11px]">
                            <span className="text-slate-500">Hint:</span>
                            <span className="text-slate-800">
                              {provider.masked_hint ?? '••••'}
                            </span>
                          </div>
                        )}
                        {provider.provider === 'BEDROCK' && (
                          <div className="text-[11px] text-slate-500">
                            IAM role / instance profile credentials
                          </div>
                        )}
                      </div>

                      {/* Catalog Status */}
                      <div className="mt-3 text-xs space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-500">Catalog Access:</span>
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold ${catalogStatusCfg.bg} ${catalogStatusCfg.text} border ${catalogStatusCfg.border}`}
                          >
                            <StatusIcon className="w-3.5 h-3.5" />
                            {catalogStatusCfg.label}
                          </span>
                        </div>

                        {provider.catalog_checked_at && (
                          <div className="flex justify-between text-[11px] text-slate-500">
                            <span>Checked:</span>
                            <span>
                              {new Date(provider.catalog_checked_at).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit',
                              })}
                              {provider.catalog_latency_ms != null &&
                                ` (${provider.catalog_latency_ms} ms)`}
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Test feedback banner */}
                      {isTestedFeedback && (
                        <div className="mt-2 p-2 rounded bg-slate-100 border border-slate-200 text-xs">
                          {testResultFeedback.error ? (
                            <span className="text-rose-700">{testResultFeedback.error}</span>
                          ) : (
                            <span className="text-slate-700">
                              Test finished: <strong>{testResultFeedback.status}</strong>
                              {testResultFeedback.latencyMs != null &&
                                ` in ${testResultFeedback.latencyMs} ms`}
                            </span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Card Action Buttons */}
                    <div className="flex items-center gap-2 pt-2 border-t border-slate-100">
                      <button
                        type="button"
                        onClick={() => setEditingProvider(provider)}
                        className="flex-1 py-1.5 px-3 text-xs font-medium border border-slate-300 rounded-lg hover:bg-slate-50 text-slate-800 text-center"
                      >
                        Configure
                      </button>
                      <button
                        type="button"
                        disabled={!provider.configured || isTesting}
                        onClick={() => handleTestCatalog(provider)}
                        title={
                          !provider.configured
                            ? 'Configure provider before verifying catalog'
                            : 'Verify catalog access'
                        }
                        className="py-1.5 px-3 text-xs font-medium text-[#1F4B7A] bg-[#1F4B7A]/5 hover:bg-[#1F4B7A]/10 border border-[#1F4B7A]/20 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-1"
                      >
                        {isTesting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                        {isTesting ? 'Verifying...' : 'Verify Catalog'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      )}

      {/* Configure Provider Modal */}
      {editingProvider && (
        <ConfigureProviderModal
          provider={editingProvider}
          onClose={() => setEditingProvider(null)}
          onSuccess={() => {
            void providersQuery.refetch();
            void routeQuery.refetch();
          }}
        />
      )}

      {/* Route Activation Modal */}
      {activatingRoute && (
        <RouteActivationModal
          route={activatingRoute}
          providerName={
            providersByCode[activatingRoute.provider]?.display_name ?? activatingRoute.provider
          }
          onClose={() => setActivatingRoute(null)}
          onSuccess={() => {
            void routeQuery.refetch();
            void providersQuery.refetch();
          }}
        />
      )}
    </div>
  );
};
