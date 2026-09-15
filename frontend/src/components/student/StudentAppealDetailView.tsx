import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  MessageSquare,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  Loader2,
  AlertCircle,
  ExternalLink,
  FileText,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';

export const StudentAppealDetailView: React.FC = () => {
  const { requestId = '' } = useParams();
  const navigate = useNavigate();

  const requestQuery = useQuery({
    queryKey: ['review-request', requestId],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/review-requests/{review_request_id}', {
          params: { path: { review_request_id: requestId } },
        }),
      ),
    enabled: Boolean(requestId),
    retry: false,
  });

  const request = requestQuery.data;

  return (
    <div className="p-6 sm:p-8 max-w-4xl mx-auto space-y-6">
      {/* Back Navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => navigate('/student/assignments')}
          className="inline-flex items-center gap-2 text-xs font-semibold text-slate-600 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back to assignments
        </button>
      </div>

      {/* Header */}
      <div className="border-b border-slate-200 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Review Request Details</h1>
            <p className="font-mono text-xs text-slate-500 mt-0.5 break-all">ID: {requestId}</p>
          </div>
          {request && (
            <div>
              {request.status === 'OPEN' ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                  <Clock className="w-3.5 h-3.5" /> Pending Instructor Review
                </span>
              ) : request.status === 'RESOLVED' ? (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Resolved
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                  <XCircle className="w-3.5 h-3.5" /> Rejected
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Loading State */}
      {requestQuery.isLoading && (
        <div className="py-16 text-center text-slate-400 flex flex-col items-center gap-2">
          <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
          <p className="text-sm">Loading review request details...</p>
        </div>
      )}

      {/* Error State */}
      {requestQuery.isError && (
        <div role="alert" className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 space-y-2">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            <span>Could not load review request</span>
          </div>
          <p className="text-xs">{getErrorMessage(requestQuery.error)}</p>
          <div className="pt-2 flex items-center gap-3">
            <button
              type="button"
              onClick={() => void requestQuery.refetch()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-800 text-white rounded-lg text-xs font-semibold hover:bg-rose-900"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
            <button
              type="button"
              onClick={() => navigate('/student/assignments')}
              className="px-3 py-1.5 border border-rose-300 text-rose-700 rounded-lg text-xs font-medium hover:bg-rose-100"
            >
              Back to assignments
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      {request && (
        <div className="space-y-6">
          {/* Instructor Response Section */}
          <section className="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs space-y-4">
            <div className="flex items-center gap-2 text-slate-900 font-bold text-sm border-b border-slate-100 pb-3">
              <MessageSquare className="w-4 h-4 text-[#1F4B7A]" />
              <h2>Instructor Decision & Feedback</h2>
            </div>

            {request.response ? (
              <div className="space-y-3">
                <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
                  <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap font-medium">
                    {request.response}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-500">
                  {request.responded_at && (
                    <span>
                      Responded on: <strong className="text-slate-700">{new Date(request.responded_at).toLocaleString()}</strong>
                    </span>
                  )}
                  {request.responded_by_user_id && (
                    <span className="font-mono">
                      Instructor ID: {request.responded_by_user_id}
                    </span>
                  )}
                </div>
              </div>
            ) : (
              <div className="p-4 rounded-xl bg-amber-50/70 border border-amber-200 text-amber-900 text-xs">
                <p className="font-medium">No instructor response yet.</p>
                <p className="text-[11px] text-amber-700 mt-0.5">
                  Your instructor is reviewing your appeal. You will be notified when a decision is made.
                </p>
              </div>
            )}
          </section>

          {/* Appeal Request Context */}
          <section className="bg-white border border-slate-200 rounded-2xl p-5 shadow-xs space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2 text-slate-900 font-bold text-sm">
                <FileText className="w-4 h-4 text-[#1F4B7A]" />
                <h2>Appeal Information</h2>
              </div>
              <span className="text-[11px] text-slate-500">
                Submitted on {new Date(request.created_at).toLocaleString()}
              </span>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">
                  Your Appeal Rationale
                </label>
                <div className="p-3.5 mt-1 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-800 leading-relaxed whitespace-pre-wrap">
                  {request.reason}
                </div>
              </div>

              {/* Exact Published Result & Metadata Context */}
              <div className="p-3.5 bg-slate-50/70 rounded-xl border border-slate-200 grid sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-slate-400 text-[10px] font-bold uppercase block">
                    Published Result ID
                  </span>
                  <span className="font-mono text-slate-700 text-[11px] break-all">
                    {request.published_result_id}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 text-[10px] font-bold uppercase block">
                    Submission ID
                  </span>
                  <span className="font-mono text-slate-700 text-[11px] break-all">
                    {request.submission_id}
                  </span>
                </div>
                {request.criterion_id && (
                  <div>
                    <span className="text-slate-400 text-[10px] font-bold uppercase block">
                      Target Criterion ID
                    </span>
                    <span className="font-mono text-slate-700 text-[11px] break-all">
                      {request.criterion_id}
                    </span>
                  </div>
                )}
                {request.finding_id && (
                  <div>
                    <span className="text-slate-400 text-[10px] font-bold uppercase block">
                      Target Finding ID
                    </span>
                    <span className="font-mono text-slate-700 text-[11px] break-all">
                      {request.finding_id}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Secondary Link to Published Result */}
            {request.submission_id && (
              <div className="pt-2 flex justify-end">
                <Link
                  to={`/student/submissions/${encodeURIComponent(request.submission_id)}/result`}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl border border-slate-300 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-slate-900 transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>View Latest Published Result</span>
                </Link>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
};
