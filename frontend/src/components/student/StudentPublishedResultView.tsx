import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, FileText, MessageSquare, RefreshCw, ShieldCheck } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';
import { AppealModal } from './AppealModal';

export const StudentPublishedResultView: React.FC = () => {
  const { submissionId = '' } = useParams();
  const navigate = useNavigate();
  const [showReviewRequest, setShowReviewRequest] = useState(false);
  const [requestStatus, setRequestStatus] = useState<string>();
  const resultQuery = useQuery({
    queryKey: ['published-result', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/published-result', {
      params: { path: { submission_id: submissionId } },
    })),
    enabled: Boolean(submissionId),
    retry: false,
  });
  const versionsQuery = useQuery({
    queryKey: ['submission-versions', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/versions', {
      params: { path: { submission_id: submissionId }, query: { page: 1, page_size: 100 } },
    })),
    enabled: Boolean(submissionId),
    retry: false,
  });
  const result = resultQuery.data;
  const criterionGroups = useMemo(() => {
    const groups = new Map<string, NonNullable<typeof result>['findings']>();
    for (const finding of result?.findings ?? []) {
      const group = groups.get(finding.criterion_version_id) ?? [];
      group.push(finding);
      groups.set(finding.criterion_version_id, group);
    }
    return [...groups.entries()];
  }, [result]);
  const versions = versionsQuery.data?.items ?? [];
  const latestDocumentVersion = versions[versions.length - 1];
  const reviewEligible = Boolean(
    result && versionsQuery.isSuccess && latestDocumentVersion?.document_version_id === result.document_version_id,
  );

  return (
    <div className="p-6 sm:p-8 max-w-5xl mx-auto space-y-6">
      <button type="button" onClick={() => navigate('/student/assignments')} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900">
        <ArrowLeft className="w-4 h-4" /> Back to assignments
      </button>

      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Published Result</h1>
        <p className="font-mono text-xs text-slate-500 mt-1 break-all">Submission {submissionId}</p>
      </div>

      {resultQuery.error && (
        <div role="alert" className="p-4 rounded-xl border border-amber-200 bg-amber-50 text-amber-800 text-sm">
          <p>{getErrorMessage(resultQuery.error)}</p>
          <p className="mt-1">Result may not be published yet, may have been unpublished, or may not belong to this account.</p>
          <button type="button" onClick={() => void resultQuery.refetch()} className="inline-flex items-center gap-2 mt-3 font-semibold underline">
            <RefreshCw className="w-4 h-4" /> Retry
          </button>
        </div>
      )}

      {requestStatus && <div role="status" className="p-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-sm">{requestStatus}</div>}
      {result && versionsQuery.isError && (
        <div role="alert" className="p-3 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm">
          Review request availability could not be verified.
        </div>
      )}
      {result && versionsQuery.isSuccess && !reviewEligible && (
        <div role="status" className="p-3 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 text-sm">
          Review requests are unavailable for this result because a newer submission exists.
        </div>
      )}

      {resultQuery.isLoading ? (
        <p className="p-8 text-center text-slate-500">Loading published result...</p>
      ) : result ? (
        <>
          <section className="bg-slate-900 text-white rounded-2xl p-6 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="inline-flex items-center gap-2 text-sm font-semibold text-emerald-300"><ShieldCheck className="w-5 h-5" /> PUBLISHED</span>
              <button
                type="button"
                disabled={criterionGroups.length === 0 || !reviewEligible}
                title={!reviewEligible ? 'Review requests require the latest submitted document result.' : undefined}
                onClick={() => setShowReviewRequest(true)}
                className="inline-flex items-center gap-2 px-3 py-2 bg-white text-slate-900 rounded-lg text-sm font-semibold disabled:opacity-40"
              >
                <MessageSquare className="w-4 h-4" /> Request criterion review
              </button>
            </div>
            <dl className="grid sm:grid-cols-2 gap-3 text-sm">
              <div><dt className="text-slate-400">Published version</dt><dd>v{result.version_number}</dd></div>
              <div><dt className="text-slate-400">Published at</dt><dd>{new Date(result.published_at).toLocaleString()}</dd></div>
              <div className="sm:col-span-2"><dt className="text-slate-400">Result ID</dt><dd className="font-mono break-all">{result.published_result_id}</dd></div>
            </dl>
            {result.comment && <div className="p-3 rounded-lg bg-slate-800 text-sm whitespace-pre-wrap"><span className="text-slate-400">Teacher comment</span><p className="mt-1">{result.comment}</p></div>}
          </section>

          <section className="space-y-3">
            <h2 className="font-bold text-slate-900">Criteria and accepted findings</h2>
            {criterionGroups.length === 0 ? (
              <p className="p-6 bg-white border border-slate-200 rounded-xl text-sm text-slate-500">No published findings.</p>
            ) : criterionGroups.map(([criterionVersionId, findings]) => (
              <article key={criterionVersionId} className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
                <h3 className="font-mono text-xs font-bold text-slate-700 break-all">Criterion {criterionVersionId}</h3>
                {findings.map((finding) => (
                  <div key={finding.finding_id} className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-xs text-slate-500 break-all">Finding {finding.finding_id}</span>
                      <span className="text-sm font-semibold text-slate-800">Score: {finding.score ?? 'none'}</span>
                    </div>
                    <p className="text-sm text-slate-800 whitespace-pre-wrap">{finding.description}</p>
                    {finding.suggestion && <p className="text-sm text-sky-800">Suggestion: {finding.suggestion}</p>}
                    <div className="space-y-1">
                      {finding.evidence.map((evidence) => (
                        <div key={`${evidence.document_ir_id}:${evidence.element_id}:${evidence.page_number}`} className="flex items-start gap-2 text-xs text-slate-600">
                          <FileText className="w-3.5 h-3.5 shrink-0" />
                          <span>Page {evidence.page_number}; bbox ({evidence.bbox.x0}, {evidence.bbox.top}, {evidence.bbox.x1}, {evidence.bbox.bottom}); element <span className="font-mono break-all">{evidence.element_id}</span></span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </article>
            ))}
          </section>
        </>
      ) : null}

      {showReviewRequest && result && reviewEligible && (
        <AppealModal
          result={result}
          onClose={() => setShowReviewRequest(false)}
          onCreated={(request) => setRequestStatus(`Review request ${request.id} created with status ${request.status}.`)}
        />
      )}
    </div>
  );
};
