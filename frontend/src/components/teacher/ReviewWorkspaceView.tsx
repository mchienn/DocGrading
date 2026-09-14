import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, LockKeyhole, Send, XCircle } from 'lucide-react';
import { useBeforeUnload, useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { ApiError, api, apiData, apiVoid, getErrorMessage } from '../../api/client';
import { PdfEvidenceViewer } from './PdfEvidenceViewer';

type Finding = components['schemas']['FindingResponse'];
type Decision = components['schemas']['ReviewDecisionRequest'];
type DraftContent = Omit<components['schemas']['ReviewDraftRequest'], 'revision'>;
type EvidenceWorkspace = components['schemas']['EvidenceWorkspaceResponse'];
type ReviewDraft = components['schemas']['ReviewDraftResponse'];
type SaveStatus = 'saved' | 'saving' | 'conflict' | 'error';

interface ReviewWorkspaceViewProps {
  role: 'teacher' | 'admin';
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


function serializeDraft(draft: DraftContent): string {
  return JSON.stringify(draft);
}

const queuePageSize = 100;

async function loadDocumentStatus(courseId: string, submissionId: string): Promise<string> {
  for (let page = 1; ; page += 1) {
    const queue = await apiData(api.GET('/api/v1/courses/{course_id}/submission-queue', {
      params: {
        path: { course_id: courseId },
        query: { sort: 'desc', page, page_size: queuePageSize },
      },
    }));
    const submission = queue.items.find((item) => item.submission_id === submissionId);
    if (submission) return submission.document_status ?? 'NO_DOCUMENT';
    if (page * queue.page_size >= queue.total) throw new Error('Submission not found in course queue');
  }
}

export const ReviewWorkspaceView: React.FC<ReviewWorkspaceViewProps> = ({ role }) => {
  const { courseId = '', submissionId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const routeState = location.state as { documentStatus?: string } | null;
  const [documentStatus, setDocumentStatus] = useState<string | undefined>(routeState?.documentStatus);
  const [reviewLock, setReviewLock] = useState<components['schemas']['ReviewLockResponse']>();
  const [lockError, setLockError] = useState<string>();
  const [draft, setDraft] = useState<DraftContent>();
  const [selectedFindingId, setSelectedFindingId] = useState<string>();
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved');
  const [saveError, setSaveError] = useState<string>();
  const [action, setAction] = useState<'approve' | 'publish'>();
  const [actionError, setActionError] = useState<string>();
  const [showPublish, setShowPublish] = useState(false);
  const [publishReason, setPublishReason] = useState('');
  const [publishedResultId, setPublishedResultId] = useState<string>();
  const [leaving, setLeaving] = useState(false);
  const revisionRef = useRef(1);
  const lastSavedRef = useRef('');
  const draftRef = useRef<DraftContent>();
  const queuedRef = useRef<DraftContent>();
  const savePromiseRef = useRef<Promise<void>>();
  const approveKeyRef = useRef(crypto.randomUUID());
  const publishAttemptRef = useRef<{ key: string; reason: string }>();
  const hydratedDocumentRef = useRef<string>();
  const navigationBypassRef = useRef(false);
  const exitPromiseRef = useRef<Promise<boolean>>();
  const publishButtonRef = useRef<HTMLButtonElement>(null);
  const publishDialogRef = useRef<HTMLDialogElement>(null);
  const publishReasonRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!showPublish) return;
    const dialog = publishDialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    publishReasonRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      publishButtonRef.current?.focus();
    };
  }, [showPublish]);

  const hydrateDraft = useCallback((evidence: EvidenceWorkspace, stored: ReviewDraft) => {
    const loaded: DraftContent = {
      document_version_id: evidence.document_version_id,
      comment: stored.comment,
      decisions: stored.decisions,
    };
    hydratedDocumentRef.current = evidence.document_version_id;
    revisionRef.current = stored.revision;
    lastSavedRef.current = serializeDraft(loaded);
    queuedRef.current = undefined;
    draftRef.current = loaded;
    setDraft(loaded);
    setSaveStatus('saved');
    setSaveError(undefined);
    setSelectedFindingId(evidence.findings[0]?.id);
  }, []);

  const evidenceQuery = useQuery({
    queryKey: ['submission-evidence', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/evidence', {
      params: { path: { submission_id: submissionId } },
    })),
    enabled: Boolean(submissionId),
  });
  const draftQuery = useQuery({
    queryKey: ['review-draft', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/review-draft', {
      params: { path: { submission_id: submissionId } },
    })),
    enabled: Boolean(submissionId),
  });
  const statusQuery = useQuery({
    queryKey: ['submission-document-status', courseId, submissionId],
    queryFn: () => loadDocumentStatus(courseId, submissionId),
    enabled: Boolean(courseId && submissionId && !routeState?.documentStatus),
  });

  useEffect(() => {
    if (statusQuery.data) setDocumentStatus(statusQuery.data);
  }, [statusQuery.data]);

  useEffect(() => {
    const evidence = evidenceQuery.data;
    const stored = draftQuery.data;
    if (!evidence || !stored || hydratedDocumentRef.current === evidence.document_version_id) return;
    hydrateDraft(evidence, stored);
  }, [draftQuery.data, evidenceQuery.data, hydrateDraft]);

  const reloadServerDraft = async () => {
    const result = await draftQuery.refetch();
    if (result.data && evidenceQuery.data) hydrateDraft(evidenceQuery.data, result.data);
  };

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  const acquireLock = useCallback(async () => {
    setLockError(undefined);
    try {
      setReviewLock(await apiData(api.POST('/api/v1/submissions/{submission_id}/review-lock', {
        params: { path: { submission_id: submissionId } },
      })));
    } catch (error) {
      setLockError(getErrorMessage(error));
    }
  }, [submissionId]);

  useEffect(() => {
    if (!submissionId || documentStatus !== 'AWAITING_REVIEW') return;
    void acquireLock();
  }, [acquireLock, documentStatus, submissionId]);

  useEffect(() => {
    if (!reviewLock?.acquired) return;
    const interval = window.setInterval(() => {
      void apiData(api.PUT('/api/v1/submissions/{submission_id}/review-lock/heartbeat', {
        params: { path: { submission_id: submissionId } },
      })).then(setReviewLock).catch((error) => {
        setReviewLock((current) => current ? { ...current, acquired: false } : current);
        setLockError(getErrorMessage(error));
      });
    }, 60_000);
    return () => window.clearInterval(interval);
  }, [reviewLock?.acquired, submissionId]);

  const drainSaves = useCallback((): Promise<void> => {
    if (savePromiseRef.current) return savePromiseRef.current;
    const savePromise = (async () => {
      while (queuedRef.current) {
        const content = queuedRef.current;
        queuedRef.current = undefined;
        setSaveStatus('saving');
        try {
          const saved = await apiData(api.PUT('/api/v1/submissions/{submission_id}/review-draft', {
            params: { path: { submission_id: submissionId } },
            body: { ...content, revision: revisionRef.current },
          }));
          revisionRef.current = saved.revision;
          lastSavedRef.current = serializeDraft(content);
          setSaveError(undefined);
          const latest = draftRef.current;
          if (!queuedRef.current && latest && serializeDraft(latest) === lastSavedRef.current) {
            setSaveStatus('saved');
          }
        } catch (error) {
          queuedRef.current = undefined;
          setSaveStatus(error instanceof ApiError && error.status === 409 ? 'conflict' : 'error');
          setSaveError(getErrorMessage(error));
          break;
        }
      }
    })();
    savePromiseRef.current = savePromise;
    void savePromise.finally(() => {
      if (savePromiseRef.current === savePromise) savePromiseRef.current = undefined;
    });
    return savePromise;
  }, [submissionId]);

  const editable = !leaving && reviewLock?.acquired === true && documentStatus === 'AWAITING_REVIEW';
  useEffect(() => {
    if (!draft || !editable || serializeDraft(draft) === lastSavedRef.current) return;
    setSaveStatus('saving');
    const timeout = window.setTimeout(() => {
      queuedRef.current = draft;
      void drainSaves();
    }, 800);
    return () => window.clearTimeout(timeout);
  }, [draft, drainSaves, editable]);

  const findings = evidenceQuery.data?.findings ?? [];
  const decisions = draft?.decisions ?? [];
  const selectedFinding = findings.find((finding) => finding.id === selectedFindingId) ?? findings[0];
  const allDecided = findings.every((finding) => decisions.some((decision) => decision.finding_id === finding.id));
  const decisionByFinding = useMemo(
    () => new Map(decisions.map((decision) => [decision.finding_id, decision])),
    [decisions],
  );

  const changeDecision = (finding: Finding, decision: Decision['decision']) => {
    setDraft((current) => {
      if (!current) return current;
      const existing = current.decisions?.find((item) => item.finding_id === finding.id);
      const next: Decision = decision === 'EDIT'
        ? {
            finding_id: finding.id,
            decision,
            edited_description: existing?.edited_description ?? finding.description,
            final_score: existing?.final_score ?? finding.proposed_score,
            reason: existing?.reason ?? null,
          }
        : {
            finding_id: finding.id,
            decision,
            reason: existing?.reason ?? null,
          };
      const currentDecisions = current.decisions ?? [];
      const index = currentDecisions.findIndex((item) => item.finding_id === next.finding_id);
      const updated = index < 0
        ? [...currentDecisions, next]
        : currentDecisions.map((item, currentIndex) => currentIndex === index ? next : item);
      return { ...current, decisions: updated };
    });
  };

  const updateDecision = (findingId: string, patch: Partial<Decision>) => {
    setDraft((current) => {
      if (!current) return current;
      const existing = current.decisions?.find((decision) => decision.finding_id === findingId);
      if (!existing) return current;
      const currentDecisions = current.decisions ?? [];
      const next = { ...existing, ...patch };
      return {
        ...current,
        decisions: currentDecisions.map((decision) => decision.finding_id === findingId ? next : decision),
      };
    });
  };

  const draftDirty = Boolean(draft && serializeDraft(draft) !== lastSavedRef.current);
  const shouldBlockNavigation = draftDirty || saveStatus === 'saving' || reviewLock?.acquired === true;
  const blocker = useBlocker(({ currentLocation, nextLocation }) =>
    !navigationBypassRef.current
    && shouldBlockNavigation
    && (
      currentLocation.pathname !== nextLocation.pathname
      || currentLocation.search !== nextLocation.search
      || currentLocation.hash !== nextLocation.hash
    ));
  const handleBeforeUnload = useCallback((event: BeforeUnloadEvent) => {
    if (!draftDirty && saveStatus !== 'saving') return;
    event.preventDefault();
    event.returnValue = '';
  }, [draftDirty, saveStatus]);
  useBeforeUnload(handleBeforeUnload);

  const prepareToLeave = useCallback((): Promise<boolean> => {
    if (exitPromiseRef.current) return exitPromiseRef.current;
    const exitPromise = (async () => {
      setLeaving(true);
      const latest = draftRef.current;
      if (latest && serializeDraft(latest) !== lastSavedRef.current) {
        queuedRef.current = latest;
        setSaveStatus('saving');
        await drainSaves();
        const savedLatest = draftRef.current;
        if (savedLatest && serializeDraft(savedLatest) !== lastSavedRef.current) {
          setLeaving(false);
          return false;
        }
      }
      if (reviewLock?.acquired) {
        try {
          await apiVoid(api.DELETE('/api/v1/submissions/{submission_id}/review-lock', {
            params: { path: { submission_id: submissionId } },
          }));
        } catch {
          // Lock expires server-side if release cannot reach API.
        }
      }
      return true;
    })();
    exitPromiseRef.current = exitPromise;
    void exitPromise.finally(() => {
      if (exitPromiseRef.current === exitPromise) exitPromiseRef.current = undefined;
    });
    return exitPromise;
  }, [drainSaves, reviewLock?.acquired, submissionId]);

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    let active = true;
    const { proceed, reset } = blocker;
    void prepareToLeave().then((ready) => {
      if (!active) return;
      if (ready) {
        navigationBypassRef.current = true;
        proceed();
      } else {
        reset();
      }
    });
    return () => { active = false; };
  }, [blocker, prepareToLeave]);

  const leave = async () => {
    if (!await prepareToLeave()) return;
    navigationBypassRef.current = true;
    navigate(`/${role}/courses/${courseId}/submissions`);
  };

  const approve = async () => {
    const versionId = evidenceQuery.data?.document_version_id;
    if (!versionId) return;
    setAction('approve');
    setActionError(undefined);
    try {
      const response = await apiData(api.POST('/api/v1/document-versions/{version_id}/approve', {
        params: {
          path: { version_id: versionId },
          header: { 'Idempotency-Key': approveKeyRef.current },
        },
      }));
      setDocumentStatus(response.status);
      try {
        await apiVoid(api.DELETE('/api/v1/submissions/{submission_id}/review-lock', {
          params: { path: { submission_id: submissionId } },
        }));
      } catch {
        // Approved document is immutable even if lock release cannot reach API.
      }
      setReviewLock((current) => current ? { ...current, acquired: false } : current);
      await queryClient.invalidateQueries({ queryKey: ['submission-queue', courseId] });
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setAction(undefined);
    }
  };

  const publish = async () => {
    const versionId = evidenceQuery.data?.document_version_id;
    const reason = publishReason.trim();
    if (!versionId || !reason) return;
    const attempt = publishAttemptRef.current ?? {
      key: crypto.randomUUID(),
      reason,
    };
    publishAttemptRef.current = attempt;
    setPublishReason(attempt.reason);
    setAction('publish');
    setActionError(undefined);
    try {
      const response = await apiData(api.POST('/api/v1/document-versions/{version_id}/publish', {
        params: {
          path: { version_id: versionId },
          header: { 'Idempotency-Key': attempt.key },
        },
        body: { reason: attempt.reason },
      }));
      setDocumentStatus('PUBLISHED');
      setPublishedResultId(response.published_result_id);
      setShowPublish(false);
      await queryClient.invalidateQueries({ queryKey: ['submission-queue', courseId] });
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setAction(undefined);
    }
  };

  const loadError = evidenceQuery.error ?? draftQuery.error ?? statusQuery.error;
  const saveLabel = saveStatus === 'saved'
    ? 'saved'
    : saveStatus === 'saving'
      ? 'saving'
      : saveStatus;

  return (
    <div className="p-4 sm:p-6 max-w-[1800px] mx-auto space-y-4">
      <header className="sticky top-2 z-30 bg-white border border-slate-200 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-sm">
        <div className="flex items-center gap-3 min-w-0">
          <button type="button" disabled={leaving} onClick={() => void leave()} className="p-2 border border-slate-300 rounded-lg disabled:opacity-40" aria-label="Back to queue">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="min-w-0">
            <h1 className="font-bold text-slate-900">Review Workspace</h1>
            <p className="font-mono text-xs text-slate-500 truncate">Submission {submissionId}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="px-2 py-1 rounded border border-slate-200 bg-slate-50 font-mono text-xs">{documentStatus ?? 'LOADING_STATUS'}</span>
          <span className={`px-2 py-1 rounded border font-mono text-xs ${saveStatus === 'conflict' ? 'border-rose-300 bg-rose-50 text-rose-700' : 'border-slate-200 bg-white text-slate-600'}`}>
            {saveLabel}
          </span>
          <button
            type="button"
            disabled={!editable || !allDecided || saveStatus !== 'saved' || action !== undefined}
            onClick={() => void approve()}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-900 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
          >
            <CheckCircle2 className="w-4 h-4" /> {action === 'approve' ? 'Approving...' : 'Approve'}
          </button>
          <button
            ref={publishButtonRef}
            type="button"
            disabled={documentStatus !== 'APPROVED' || action !== undefined}
            onClick={() => setShowPublish(true)}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
          >
            <Send className="w-4 h-4" /> Publish
          </button>
        </div>
      </header>

      {(loadError || lockError || saveError || actionError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm flex items-start justify-between gap-3">
          <span>{actionError ?? saveError ?? lockError ?? getErrorMessage(loadError)}</span>
          {lockError && documentStatus === 'AWAITING_REVIEW' && (
            <button type="button" onClick={() => void acquireLock()} className="underline shrink-0">Retry lock</button>
          )}
          {(saveStatus === 'conflict' || saveStatus === 'error') && draft && (
            <span className="flex gap-2 shrink-0">
              <button type="button" onClick={() => void reloadServerDraft()} className="underline">Reload server draft</button>
              {saveStatus === 'error' && <button type="button" onClick={() => { queuedRef.current = draft; void drainSaves(); }} className="underline">Retry save</button>}
            </span>
          )}
        </div>
      )}

      {publishedResultId && (
        <div role="status" className="p-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-sm">
          Published result <span className="font-mono break-all">{publishedResultId}</span>
        </div>
      )}

      {documentStatus === 'AWAITING_REVIEW' && !reviewLock?.acquired && !lockError && (
        <div className="p-3 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2">
            <LockKeyhole className="w-4 h-4" />
            {reviewLock ? `Read-only: locked by ${reviewLock.reviewer_display_name ?? 'another reviewer'} until ${reviewLock.expires_at ? new Date(reviewLock.expires_at).toLocaleString() : 'expiry'}.` : 'Acquiring review lock...'}
          </span>
          {reviewLock && <button type="button" onClick={() => void acquireLock()} className="underline shrink-0">Retry lock</button>}
        </div>
      )}

      {evidenceQuery.isLoading || draftQuery.isLoading ? (
        <p className="p-8 text-center text-slate-500">Loading evidence and review draft...</p>
      ) : !evidenceQuery.data || !draft ? null : (
        <div className="grid lg:grid-cols-[minmax(0,2fr)_minmax(360px,1fr)] gap-4 items-start">
          <PdfEvidenceViewer
            documentVersionId={evidenceQuery.data.document_version_id}
            findings={findings}
            selectedFindingId={selectedFinding?.id}
            onSelectFinding={setSelectedFindingId}
          />

          <section className="bg-white border border-slate-200 rounded-xl p-5 space-y-4" aria-label="Review decisions">
            <label className="block text-sm font-semibold text-slate-800">
              Review comment
              <textarea
                rows={4}
                maxLength={10_000}
                disabled={!editable}
                value={draft.comment}
                onChange={(event) => setDraft((current) => current ? { ...current, comment: event.target.value } : current)}
                className="block w-full mt-2 p-3 border border-slate-300 rounded-lg font-normal disabled:bg-slate-100"
              />
            </label>

            <div className="space-y-3">
              {findings.map((finding) => {
                const decision = decisionByFinding.get(finding.id);
                return (
                  <article
                    key={finding.id}
                    className={`p-4 rounded-xl border ${selectedFinding?.id === finding.id ? 'border-sky-500 bg-sky-50/40' : 'border-slate-200'}`}
                  >
                    <button type="button" onClick={() => setSelectedFindingId(finding.id)} className="w-full text-left">
                      <span className="font-mono text-[11px] text-slate-500">{finding.severity} · Criterion {finding.criterion_version_id}</span>
                      <p className="mt-1 text-sm text-slate-800">{finding.description}</p>
                      <span className="block mt-1 text-xs text-slate-500">Proposed score: {finding.proposed_score ?? 'none'} · Evidence: {finding.evidence.length}</span>
                    </button>
                    <div className="flex gap-2 mt-3">
                      {(['ACCEPT', 'EDIT', 'REJECT'] as const).map((value) => (
                        <button
                          key={value}
                          type="button"
                          disabled={!editable}
                          onClick={() => changeDecision(finding, value)}
                          className={`px-2.5 py-1.5 rounded-lg border text-xs font-semibold disabled:opacity-40 ${decision?.decision === value ? 'bg-slate-900 border-slate-900 text-white' : 'border-slate-300 bg-white text-slate-700'}`}
                        >
                          {value}
                        </button>
                      ))}
                    </div>
                    {decision?.decision === 'EDIT' && (
                      <div className="grid gap-2 mt-3">
                        <label className="text-xs text-slate-600">Edited description
                          <textarea
                            maxLength={10_000}
                            rows={3}
                            disabled={!editable}
                            value={decision.edited_description ?? ''}
                            onChange={(event) => updateDecision(finding.id, { edited_description: event.target.value || null })}
                            className="block w-full mt-1 p-2 border border-slate-300 rounded-lg"
                          />
                        </label>
                        <label className="text-xs text-slate-600">Final score
                          <input
                            type="number"
                            min={0}
                            max={100}
                            step={0.01}
                            disabled={!editable}
                            value={decision.final_score ?? ''}
                            onChange={(event) => updateDecision(finding.id, { final_score: event.target.value || null })}
                            className="block w-full mt-1 p-2 border border-slate-300 rounded-lg"
                          />
                        </label>
                      </div>
                    )}
                    {decision && decision.decision !== 'ACCEPT' && (
                      <label className="block mt-3 text-xs text-slate-600">Override reason {decision.decision === 'REJECT' ? '(required)' : '(required when score changes)'}
                        <textarea
                          rows={2}
                          maxLength={2_000}
                          disabled={!editable}
                          value={decision.reason ?? ''}
                          onChange={(event) => updateDecision(finding.id, { reason: event.target.value || null })}
                          className="block w-full mt-1 p-2 border border-slate-300 rounded-lg"
                        />
                      </label>
                    )}
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      )}

      {showPublish && (
        <dialog
          ref={publishDialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="publish-title"
          tabIndex={-1}
          onKeyDown={trapFocus}
          onCancel={(event) => {
            event.preventDefault();
            setShowPublish(false);
          }}
          className="m-auto w-[calc(100%-2rem)] max-w-md space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-xl backdrop:bg-slate-900/60"
        >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="publish-title" className="font-bold text-slate-900">Confirm publish</h2>
                <p className="text-sm text-rose-700 mt-1">Students see result immediately. Reversal requires separate audited unpublish.</p>
              </div>
              <button type="button" onClick={() => setShowPublish(false)} aria-label="Close publish dialog"><XCircle className="w-5 h-5" /></button>
            </div>
            <label className="block text-sm font-semibold text-slate-700">Publish reason
              <textarea
                ref={publishReasonRef}
                required
                maxLength={2_000}
                rows={3}
                disabled={Boolean(publishAttemptRef.current) || action === 'publish'}
                value={publishReason}
                onChange={(event) => setPublishReason(event.target.value)}
                className="block w-full mt-2 p-3 border border-slate-300 rounded-lg font-normal"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowPublish(false)} className="px-3 py-2 border border-slate-300 rounded-lg text-sm">Cancel</button>
              <button
                type="button"
                disabled={!publishReason.trim() || action === 'publish'}
                onClick={() => void publish()}
                className="px-3 py-2 bg-emerald-700 text-white rounded-lg text-sm font-semibold disabled:opacity-40"
              >
                {action === 'publish' ? 'Publishing...' : 'Confirm publish'}
              </button>
            </div>
        </dialog>
      )}
    </div>
  );
};
