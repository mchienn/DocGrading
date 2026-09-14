import React, { useEffect, useMemo, useRef, useState } from 'react';
import { MessageSquare, Send, X } from 'lucide-react';
import type { components } from '../../api/schema';
import { api, apiData, getErrorMessage } from '../../api/client';

type PublishedResult = components['schemas']['PublishedResultResponse'];
type ReviewRequest = components['schemas']['ReviewRequestResponse'];

interface AppealModalProps {
  result: PublishedResult;
  onClose: () => void;
  onCreated: (request: ReviewRequest) => void;
}
function trapFocus(event: React.KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== 'Tab') return;
  const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
    'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
  ));
  const first = elements[0];
  const last = elements.at(-1);
  const wrap = event.shiftKey
    ? document.activeElement === first || document.activeElement === event.currentTarget
    : document.activeElement === last;
  if (!wrap) return;
  event.preventDefault();
  (event.shiftKey ? last : first)?.focus();
}


export const AppealModal: React.FC<AppealModalProps> = ({ result, onClose, onCreated }) => {
  const criteria = useMemo(() => {
    const firstFindingByCriterion = new Map<string, string>();
    for (const finding of result.findings) {
      if (!firstFindingByCriterion.has(finding.criterion_version_id)) {
        firstFindingByCriterion.set(finding.criterion_version_id, finding.finding_id);
      }
    }
    return [...firstFindingByCriterion.entries()];
  }, [result.findings]);
  const [findingId, setFindingId] = useState(criteria[0]?.[1] ?? '');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    dialog.showModal();
    dialog.focus();
    return () => {
      if (dialog.open) dialog.close();
      restoreFocusRef.current?.focus();
    };
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!findingId || !reason.trim()) return;
    setSending(true);
    setError(undefined);
    try {
      const request = await apiData(api.POST('/api/v1/published-results/{published_result_id}/review-requests', {
        params: { path: { published_result_id: result.published_result_id } },
        body: {
          submission_id: result.submission_id,
          finding_id: findingId,
          reason: reason.trim(),
        },
      }));
      onCreated(request);
      onClose();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSending(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-request-title"
      tabIndex={-1}
      onKeyDown={trapFocus}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-xl backdrop:bg-slate-900/60"
    >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="review-request-title" className="font-bold text-slate-900 inline-flex items-center gap-2"><MessageSquare className="w-4 h-4" /> Request criterion review</h2>
            <p className="text-xs text-slate-500 mt-1">One OPEN request allowed per criterion and published result.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close review request dialog"><X className="w-5 h-5" /></button>
        </div>

        {error && <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">{error}</div>}

        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm font-semibold text-slate-700">Criterion
            <select
              required
              value={findingId}
              onChange={(event) => setFindingId(event.target.value)}
              className="block w-full mt-2 p-3 border border-slate-300 rounded-lg bg-white font-mono text-xs"
            >
              {criteria.map(([criterionVersionId, firstFindingId]) => (
                <option key={criterionVersionId} value={firstFindingId}>{criterionVersionId}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-semibold text-slate-700">Reason
            <textarea
              required
              maxLength={4_000}
              rows={5}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="block w-full mt-2 p-3 border border-slate-300 rounded-lg font-normal"
            />
          </label>
          {criteria.length === 0 && <p className="text-sm text-amber-700">Published result has no criterion finding available for review request.</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-2 border border-slate-300 rounded-lg text-sm">Cancel</button>
            <button
              type="submit"
              disabled={sending || !findingId || !reason.trim()}
              className="inline-flex items-center gap-2 px-3 py-2 bg-slate-900 text-white rounded-lg text-sm font-semibold disabled:opacity-40"
            >
              <Send className="w-4 h-4" /> {sending ? 'Sending...' : 'Send request'}
            </button>
          </div>
        </form>
    </dialog>
  );
};
