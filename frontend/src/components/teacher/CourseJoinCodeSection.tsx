import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Calendar, Check, Copy, KeyRound, RefreshCw, XCircle } from 'lucide-react';
import { api, apiData, ApiError, getErrorMessage } from '../../api/client';

interface CourseJoinCodeSectionProps {
  courseId: string;
  isArchived: boolean;
}

function toDateTimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const year = date.getFullYear();
  const month = pad(date.getMonth() + 1);
  const day = pad(date.getDate());
  const hours = pad(date.getHours());
  const minutes = pad(date.getMinutes());
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}
function getRemainingText(expiresAt: string, now: number): string {
  const diff = new Date(expiresAt).getTime() - now;
  if (diff <= 0) return 'Expired';
  const totalSeconds = Math.floor(diff / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0 || days > 0) parts.push(`${hours}h`);
  if (minutes > 0 || hours > 0 || days > 0) parts.push(`${minutes}m`);
  parts.push(`${seconds}s`);
  return `${parts.join(' ')} remaining`;
}

export const CourseJoinCodeSection: React.FC<CourseJoinCodeSectionProps> = ({ courseId, isArchived }) => {
  const queryClient = useQueryClient();
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [createExpiry, setCreateExpiry] = useState(() => toDateTimeLocal(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)));
  const [isEditingExpiry, setIsEditingExpiry] = useState(false);
  const [editExpiry, setEditExpiry] = useState('');
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenExpiry, setRegenExpiry] = useState(() => toDateTimeLocal(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)));

  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const joinCodeQuery = useQuery({
    queryKey: ['course-join-code', courseId],
    queryFn: async () => {
      try {
        return await apiData(
          api.GET('/api/v1/courses/{course_id}/join-code', {
            params: { path: { course_id: courseId } },
          }),
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return null;
        }
        throw err;
      }
    },
    enabled: Boolean(courseId),
  });

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['course-join-code', courseId] }),
      queryClient.invalidateQueries({ queryKey: ['course', courseId] }),
      queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
    ]);
  };

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!createExpiry || submitting) return;
    setSubmitting(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await apiData(
        api.POST('/api/v1/courses/{course_id}/join-code', {
          params: { path: { course_id: courseId } },
          body: { expires_at: new Date(createExpiry).toISOString() },
        }),
      );
      setActionNotice('Join code created successfully.');
      await invalidate();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateExpiry = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editExpiry || submitting) return;
    setSubmitting(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await apiData(
        api.PUT('/api/v1/courses/{course_id}/join-code', {
          params: { path: { course_id: courseId } },
          body: { expires_at: new Date(editExpiry).toISOString() },
        }),
      );
      setActionNotice('Expiration updated successfully.');
      setIsEditingExpiry(false);
      await invalidate();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async () => {
    if (submitting) return;
    setSubmitting(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await apiData(
        api.DELETE('/api/v1/courses/{course_id}/join-code', {
          params: { path: { course_id: courseId } },
        }),
      );
      setActionNotice('Join code revoked.');
      await invalidate();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegenerate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!regenExpiry || submitting) return;
    setSubmitting(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await apiData(
        api.POST('/api/v1/courses/{course_id}/join-code/regenerate', {
          params: { path: { course_id: courseId } },
          body: { expires_at: new Date(regenExpiry).toISOString() },
        }),
      );
      setActionNotice('Join code regenerated successfully.');
      setIsRegenerating(false);
      await invalidate();
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopyLink = async () => {
    if (!joinCode?.join_url) return;
    try {
      await navigator.clipboard.writeText(joinCode.join_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setActionError('Failed to copy link to clipboard.');
    }
  };

  const joinCode = joinCodeQuery.data;
  const isRevoked = Boolean(joinCode?.revoked_at) || joinCode?.status === 'REVOKED';
  const isExpired = joinCode ? new Date(joinCode.expires_at).getTime() <= now : false;
  const effectiveStatus = isRevoked ? 'REVOKED' : isExpired ? 'EXPIRED' : (joinCode?.status ?? 'ACTIVE');

  return (
    <section aria-label="Course join code" className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <KeyRound className="w-4 h-4 text-sky-700" /> Course Join Code & Link
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Students can join this course using the code, direct link, or QR code.
          </p>
        </div>
      </div>

      {actionNotice && (
        <div role="status" className="p-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-xs font-medium flex items-center justify-between">
          <span>{actionNotice}</span>
          <button type="button" onClick={() => setActionNotice(null)} className="text-emerald-700 hover:text-emerald-900 font-semibold">Dismiss</button>
        </div>
      )}

      {actionError && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-xs font-medium flex items-center justify-between">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError(null)} className="text-rose-700 hover:text-rose-900 font-semibold">Dismiss</button>
        </div>
      )}

      {joinCodeQuery.isLoading ? (
        <p role="status" className="text-xs text-slate-500 py-2">Loading join code details...</p>
      ) : joinCodeQuery.error ? (
        <p role="alert" className="text-xs text-rose-700 py-2">{getErrorMessage(joinCodeQuery.error)}</p>
      ) : !joinCode ? (
        <div>
          {isArchived ? (
            <p className="text-xs text-slate-500 italic">No active join code exists for this archived course.</p>
          ) : (
            <form onSubmit={handleCreate} className="flex flex-col sm:flex-row sm:items-end gap-3 pt-1">
              <div>
                <label htmlFor="create-expiry-input" className="block text-xs font-semibold text-slate-700 mb-1">
                  Expiration date & time
                </label>
                <input
                  id="create-expiry-input"
                  type="datetime-local"
                  value={createExpiry}
                  min={toDateTimeLocal(new Date())}
                  onChange={(e) => setCreateExpiry(e.target.value)}
                  required
                  className="block px-3 py-1.5 border border-slate-300 rounded-lg text-xs bg-white text-slate-900"
                />
              </div>
              <button
                type="submit"
                disabled={submitting || !createExpiry}
                className="px-4 py-2 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-xs font-semibold disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                <KeyRound className="w-3.5 h-3.5" />
                {submitting ? 'Generating...' : 'Generate join code'}
              </button>
            </form>
          )}
        </div>
      ) : (
        <div className="space-y-4 pt-1">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 p-4 rounded-lg bg-slate-50/80 border border-slate-200">
            <div className="space-y-2 min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-xl font-bold tracking-wider text-slate-900 select-all">
                  {joinCode.code}
                </span>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ${
                    effectiveStatus === 'ACTIVE'
                      ? 'bg-emerald-100 text-emerald-800 border border-emerald-300'
                      : effectiveStatus === 'EXPIRED'
                        ? 'bg-amber-100 text-amber-800 border border-amber-300'
                        : 'bg-rose-100 text-rose-800 border border-rose-300'
                  }`}
                >
                  {effectiveStatus}
                </span>
                <span className="text-xs font-medium text-slate-600">
                  {isRevoked
                    ? `Revoked on ${new Date(joinCode.revoked_at!).toLocaleString()}`
                    : isExpired
                      ? `Expired on ${new Date(joinCode.expires_at).toLocaleString()}`
                      : `${getRemainingText(joinCode.expires_at, now)} (expires ${new Date(joinCode.expires_at).toLocaleString()})`}
                </span>
              </div>

              <div className="flex items-center gap-2 max-w-xl">
                <div className="font-mono text-xs text-slate-600 bg-white border border-slate-200 px-2.5 py-1.5 rounded truncate flex-1 select-all">
                  {joinCode.join_url}
                </div>
                <button
                  type="button"
                  aria-label="Copy join link"
                  onClick={handleCopyLink}
                  className="px-3 py-1.5 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 rounded text-xs font-semibold inline-flex items-center gap-1.5 shrink-0"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? 'Copied' : 'Copy link'}
                </button>
              </div>
            </div>

            <div className="flex items-center gap-3 shrink-0 self-start lg:self-center">
              <img
                key={joinCode.code}
                src={joinCode.qr_url}
                alt="Course join QR code"
                className="w-24 h-24 border border-slate-200 rounded-lg p-1 bg-white shadow-sm"
              />
            </div>
          </div>

          {!isArchived && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {effectiveStatus !== 'REVOKED' && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => {
                    setEditExpiry(toDateTimeLocal(new Date(joinCode.expires_at)));
                    setIsEditingExpiry(!isEditingExpiry);
                    setIsRegenerating(false);
                    setActionError(null);
                  }}
                  className="px-3 py-1.5 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50"
                >
                  <Calendar className="w-3.5 h-3.5" />
                  {isEditingExpiry ? 'Cancel expiry update' : 'Update expiry'}
                </button>
              )}

              <button
                type="button"
                disabled={submitting}
                onClick={() => {
                  setRegenExpiry(toDateTimeLocal(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)));
                  setIsRegenerating(!isRegenerating);
                  setIsEditingExpiry(false);
                  setActionError(null);
                }}
                className="px-3 py-1.5 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                {isRegenerating ? 'Cancel regenerate' : 'Regenerate code'}
              </button>

              {effectiveStatus !== 'REVOKED' && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={handleRevoke}
                  className="px-3 py-1.5 border border-rose-200 bg-white hover:bg-rose-50 text-rose-700 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 disabled:opacity-50"
                >
                  <XCircle className="w-3.5 h-3.5" />
                  Revoke code
                </button>
              )}
            </div>
          )}

          {!isArchived && isEditingExpiry && (
            <form onSubmit={handleUpdateExpiry} className="p-3 bg-slate-50 border border-slate-200 rounded-lg flex flex-col sm:flex-row sm:items-end gap-3">
              <div>
                <label htmlFor="edit-expiry-input" className="block text-xs font-semibold text-slate-700 mb-1">
                  New expiration date & time
                </label>
                <input
                  id="edit-expiry-input"
                  type="datetime-local"
                  value={editExpiry}
                  min={toDateTimeLocal(new Date())}
                  onChange={(e) => setEditExpiry(e.target.value)}
                  required
                  className="block px-3 py-1.5 border border-slate-300 rounded-lg text-xs bg-white text-slate-900"
                />
              </div>
              <button
                type="submit"
                disabled={submitting || !editExpiry}
                className="px-4 py-2 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                {submitting ? 'Saving...' : 'Save new expiration'}
              </button>
            </form>
          )}

          {!isArchived && isRegenerating && (
            <form onSubmit={handleRegenerate} className="p-3 bg-slate-50 border border-slate-200 rounded-lg flex flex-col sm:flex-row sm:items-end gap-3">
              <div>
                <label htmlFor="regen-expiry-input" className="block text-xs font-semibold text-slate-700 mb-1">
                  New code expiration date & time
                </label>
                <input
                  id="regen-expiry-input"
                  type="datetime-local"
                  value={regenExpiry}
                  min={toDateTimeLocal(new Date())}
                  onChange={(e) => setRegenExpiry(e.target.value)}
                  required
                  className="block px-3 py-1.5 border border-slate-300 rounded-lg text-xs bg-white text-slate-900"
                />
              </div>
              <button
                type="submit"
                disabled={submitting || !regenExpiry}
                className="px-4 py-2 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                {submitting ? 'Regenerating...' : 'Confirm regenerate'}
              </button>
            </form>
          )}
        </div>
      )}
    </section>
  );
};
