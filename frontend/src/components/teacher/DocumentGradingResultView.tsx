import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, CheckCircle2, Clock3, FileText, History, UserRound } from 'lucide-react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { api, apiData, getErrorMessage } from '../../api/client';
import { getFindingPresentation, PdfEvidenceViewer } from './PdfEvidenceViewer';

type GradingResult = components['schemas']['DocumentGradingResultResponse'];
type Finding = components['schemas']['FindingResponse'];
type ReviewDecision = components['schemas']['GradingReviewDecisionResponse'];

function formatState(state: Record<string, string | null>): string {
  return Object.entries(state)
    .map(([key, value]) => `${key}: ${value ?? 'none'}`)
    .join(' · ');
}

export const DocumentGradingResultView: React.FC = () => {
  const { courseId, versionId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [selectedFindingId, setSelectedFindingId] = useState<string>();
  const role = location.pathname.startsWith('/admin') ? 'admin' : 'teacher';
  const parentPath = courseId ? `/${role}/courses/${courseId}` : `/${role}/courses`;
  const resultQuery = useQuery({
    queryKey: ['document-grading-result', versionId],
    queryFn: () => apiData(api.GET('/api/v1/document-versions/{version_id}/grading-result', {
      params: { path: { version_id: versionId } },
    })),
    enabled: Boolean(versionId),
    retry: false,
  });
  const result = resultQuery.data;

  useEffect(() => {
    if (!selectedFindingId && result?.findings[0]) {
      setSelectedFindingId(result.findings[0].id);
    }
  }, [result, selectedFindingId]);

  const decisionsByFinding = useMemo(() => {
    const decisions = new Map<string, Array<{ reviewer: string; decision: ReviewDecision }>>();
    for (const review of result?.reviews ?? []) {
      for (const decision of review.decisions) {
        const existing = decisions.get(decision.finding_id) ?? [];
        existing.push({ reviewer: review.reviewer_display_name, decision });
        decisions.set(decision.finding_id, existing);
      }
    }
    return decisions;
  }, [result]);

  return (
    <div className="p-6 sm:p-8 max-w-[1680px] mx-auto space-y-6">
      <button
        type="button"
        onClick={() => navigate(parentPath)}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to course
      </button>

      {resultQuery.isLoading && <p className="p-8 text-center text-sm text-slate-500">Loading grading result...</p>}
      {resultQuery.error && (
        <div role="alert" className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-sm text-rose-800">
          {getErrorMessage(resultQuery.error)}
        </div>
      )}

      {result && <ResultContent result={result} decisionsByFinding={decisionsByFinding} selectedFindingId={selectedFindingId} onSelectFinding={setSelectedFindingId} />}
    </div>
  );
};

interface ResultContentProps {
  result: GradingResult;
  decisionsByFinding: Map<string, Array<{ reviewer: string; decision: ReviewDecision }>>;
  selectedFindingId?: string;
  onSelectFinding: (findingId: string) => void;
}

const ResultContent: React.FC<ResultContentProps> = ({
  result,
  decisionsByFinding,
  selectedFindingId,
  onSelectFinding,
}) => (
  <>
    <header className="border-b border-slate-200 pb-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-sky-700">Attempt #{result.version_number}</p>
          <h1 className="mt-1 text-2xl font-bold text-slate-900">Grading result</h1>
          <p className="mt-1 text-sm text-slate-600">{result.assignment_title} · {result.student_display_name} ({result.student_email})</p>
        </div>
        <span className="rounded-full border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs font-bold text-slate-700">
          {result.current_status}
        </span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <div><dt className="text-xs text-slate-500">File</dt><dd className="font-semibold break-all">{result.filename}</dd></div>
        <div><dt className="text-xs text-slate-500">Size</dt><dd>{result.file_size_bytes.toLocaleString()} bytes</dd></div>
        <div><dt className="text-xs text-slate-500">Submitted</dt><dd>{new Date(result.submitted_at).toLocaleString()}</dd></div>
        <div><dt className="text-xs text-slate-500">Findings</dt><dd>{result.findings.length}</dd></div>
      </dl>
      {result.failure_code && <p className="mt-3 text-sm text-rose-700">Failure code: <span className="font-mono">{result.failure_code}</span></p>}
    </header>

    <section className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(340px,2fr)]">
      <PdfEvidenceViewer
        documentVersionId={result.document_version_id}
        findings={result.findings}
        selectedFindingId={selectedFindingId}
        onSelectFinding={onSelectFinding}
      />
      <div className="max-h-[78vh] space-y-3 overflow-y-auto pr-1">
        <h2 className="sticky top-0 z-10 bg-[#F5F7FA] pb-2 font-bold text-slate-900">Marked findings</h2>
        {result.findings.length === 0 ? (
          <p className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500">No findings recorded for this attempt.</p>
        ) : result.findings.map((finding: Finding, index) => {
          const presentation = getFindingPresentation(finding.id);
          const decisions = decisionsByFinding.get(finding.id) ?? [];
          const selected = selectedFindingId === finding.id;
          return (
            <button
              key={finding.id}
              type="button"
              onClick={() => onSelectFinding(finding.id)}
              className={`w-full rounded-xl border bg-white p-4 text-left transition ${selected ? 'border-sky-500 ring-2 ring-sky-100' : 'border-slate-200 hover:border-slate-300'}`}
            >
              <div className="flex items-start gap-3">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold" style={{ backgroundColor: presentation.badgeBg, color: presentation.badgeText }}>
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold text-slate-900">{finding.criterion_code} · {finding.criterion_title}</p>
                    <span className="font-mono text-[11px] text-slate-500">{finding.severity}</span>
                  </div>
                  <p className="text-sm text-slate-700 whitespace-pre-wrap">{finding.description}</p>
                  {finding.suggestion && <p className="text-xs text-sky-800">Suggestion: {finding.suggestion}</p>}
                  <p className="text-xs text-slate-500">Proposed score: {finding.proposed_score ?? 'none'} · {finding.evidence.length} marker(s)</p>
                  {decisions.map(({ reviewer, decision }) => (
                    <div key={`${reviewer}:${decision.created_at}`} className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
                      <p className="font-bold">{reviewer}: {decision.decision}</p>
                      {decision.edited_description && <p className="mt-1 whitespace-pre-wrap">Edited: {decision.edited_description}</p>}
                      {decision.final_score !== null && <p className="mt-1">Final score: {decision.final_score}</p>}
                      {decision.edited_semantic_verdict && <p className="mt-1">Semantic verdict: {decision.edited_semantic_verdict}</p>}
                      {decision.reason && <p className="mt-1">Reason: {decision.reason}</p>}
                    </div>
                  ))}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>

    <section className="grid gap-5 lg:grid-cols-2">
      <article className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="flex items-center gap-2 font-bold text-slate-900"><Clock3 className="h-4 w-4 text-sky-700" /> Status history</h2>
        <ol className="mt-4 space-y-3">
          {result.status_history.map((event, index) => (
            <li key={`${event.changed_at}:${event.to_status}:${index}`} className="flex gap-3 text-sm">
              <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-sky-600" />
              <div>
                <p className="font-semibold text-slate-800">{event.from_status ? `${event.from_status} → ` : ''}{event.to_status}</p>
                <p className="text-xs text-slate-500">{new Date(event.changed_at).toLocaleString()}{event.recorded ? '' : ' · reconstructed from saved records'}</p>
              </div>
            </li>
          ))}
        </ol>
      </article>

      <article className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="flex items-center gap-2 font-bold text-slate-900"><UserRound className="h-4 w-4 text-sky-700" /> Teacher review</h2>
        {result.reviews.length === 0 ? (
          <p className="mt-4 text-sm text-slate-500">No teacher review saved for this attempt.</p>
        ) : result.reviews.map((review) => (
          <div key={review.id} className="mt-4 rounded-lg border border-slate-200 p-4 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <p className="font-semibold text-slate-900">{review.reviewer_display_name}</p>
              <p className="text-xs text-slate-500">Updated {new Date(review.updated_at).toLocaleString()} · revision {review.revision}</p>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-slate-700">{review.comment || 'No overall comment.'}</p>
            <p className="mt-2 text-xs text-slate-500">{review.decisions.length} finding decision(s)</p>
          </div>
        ))}
        {result.published_results.map((published) => (
          <div key={published.published_result_id} className="mt-3 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <p>Published result v{published.version_number} at {new Date(published.published_at).toLocaleString()} with {published.findings.length} finding(s).</p>
          </div>
        ))}
      </article>
    </section>

    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <h2 className="flex items-center gap-2 font-bold text-slate-900"><History className="h-4 w-4 text-sky-700" /> Recorded actions</h2>
      {result.actions.length === 0 ? (
        <p className="mt-4 text-sm text-slate-500">No recorded actions for this attempt.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-xs text-slate-500"><tr><th className="py-2 pr-4">Time</th><th className="py-2 pr-4">Actor</th><th className="py-2 pr-4">Action</th><th className="py-2">Change</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {result.actions.map((action) => (
                <tr key={action.id}>
                  <td className="py-3 pr-4 whitespace-nowrap">{new Date(action.occurred_at).toLocaleString()}</td>
                  <td className="py-3 pr-4">{action.actor_display_name}</td>
                  <td className="py-3 pr-4"><span className="font-mono text-xs">{action.action}</span><p className="mt-1 text-xs text-slate-500">{action.reason}</p></td>
                  <td className="py-3 text-xs text-slate-600"><p>{formatState(action.before) || 'none'}</p><p className="mt-1"><FileText className="mr-1 inline h-3 w-3" />{formatState(action.after) || 'none'}</p></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  </>
);
