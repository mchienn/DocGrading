import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, ArrowLeft, CheckCircle2, Clock3, LoaderCircle, RotateCcw } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { WorkspaceRole } from '../../types/api';

interface StudentStatusTimelineViewProps {
  activeRole: WorkspaceRole;
}

const friendlyErrors: Record<string, string> = {
  NOT_A_PDF: 'Uploaded file is not a PDF.',
  PDF_ENCRYPTED: 'Encrypted PDFs are not supported.',
  PDF_TOO_LARGE: 'PDF exceeds file-size limits.',
  PDF_DECODED_TOO_LARGE: 'Decoded PDF content exceeds processing limits.',
  PDF_PAGE_LIMIT: 'PDF exceeds page-count limits.',
  PDF_ACTIVE_CONTENT: 'PDF contains unsupported active content or attachments.',
  PDF_SCAN_ONLY: 'PDF needs a usable text layer; scanned documents are not supported.',
  PDF_MALFORMED: 'PDF structure is invalid or unsupported.',
  PDF_STORAGE_ERROR: 'Storage is temporarily unavailable.',
};

export const StudentStatusTimelineView: React.FC<StudentStatusTimelineViewProps> = ({ activeRole }) => {
  const { jobId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [retryError, setRetryError] = useState<string>();
  const [retrying, setRetrying] = useState(false);

  const jobQuery = useQuery({
    queryKey: ['analysis-job', jobId],
    queryFn: () => apiData(api.GET('/api/v1/analysis-jobs/{job_id}', {
      params: { path: { job_id: jobId } },
    })),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const job = query.state.data;
      if (job && (job.status === 'DONE' || job.status === 'ERROR')) return false;
      return Math.min(2_000 * 2 ** query.state.dataUpdateCount, 10_000);
    },
  });
  const job = jobQuery.data;

  const retry = async () => {
    if (!job) return;
    setRetrying(true);
    setRetryError(undefined);
    try {
      await apiData(api.POST('/api/v1/analysis-jobs/{job_id}/retry', {
        params: { path: { job_id: job.id } },
      }));
      await queryClient.invalidateQueries({ queryKey: ['analysis-job', job.id] });
    } catch (requestError) {
      setRetryError(getErrorMessage(requestError));
    } finally {
      setRetrying(false);
    }
  };

  const statusContent = () => {
    if (!job) return null;
    if (job.status === 'DONE') {
      return {
        icon: <CheckCircle2 className="w-10 h-10 text-emerald-600" />,
        title: 'PDF processing completed',
        detail: 'Ingestion and validation finished. Evaluation results are not available in current scope.',
      };
    }
    if (job.status === 'ERROR') {
      const detail = job.error_code
        ? friendlyErrors[job.error_code] ?? 'PDF processing failed. Contact support with job ID.'
        : 'PDF processing failed. Contact support with job ID.';
      return {
        icon: <AlertCircle className="w-10 h-10 text-rose-600" />,
        title: 'Processing failed',
        detail,
      };
    }
    if (job.status === 'RUNNING') {
      return {
        icon: <LoaderCircle className="w-10 h-10 text-sky-600 animate-spin" />,
        title: 'Processing PDF',
        detail: 'DocGrading is validating and extracting the uploaded document.',
      };
    }
    return {
      icon: <Clock3 className="w-10 h-10 text-amber-600" />,
      title: 'Queued',
      detail: 'Upload completed. Processing will start shortly.',
    };
  };
  const content = statusContent();

  return (
    <div className="p-6 sm:p-8 max-w-3xl mx-auto space-y-6">
      <button
        type="button"
        onClick={() => navigate(activeRole === 'student' ? '/student/assignments' : `/${activeRole}/courses`)}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Processing status</h1>
        <p className="text-sm text-slate-500 mt-1 font-mono break-all">Job {jobId}</p>
      </div>

      {(jobQuery.error || retryError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {retryError ?? getErrorMessage(jobQuery.error)}
        </div>
      )}

      {!content ? (
        jobQuery.error ? null : <p className="text-sm text-slate-500">Loading job...</p>
      ) : (
        <section className="bg-white border border-slate-200 rounded-xl p-8 text-center">
          <div className="flex justify-center">{content.icon}</div>
          <h2 className="text-xl font-bold text-slate-900 mt-4">{content.title}</h2>
          <p className="text-sm text-slate-600 mt-2">{content.detail}</p>
          <dl className="grid grid-cols-2 gap-3 mt-6 text-left max-w-md mx-auto">
            <div className="p-3 bg-slate-50 rounded-lg">
              <dt className="text-xs text-slate-500">Attempt</dt>
              <dd className="text-sm font-semibold text-slate-900">{job.attempt_count} / {job.max_attempts}</dd>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg">
              <dt className="text-xs text-slate-500">Status</dt>
              <dd className="text-sm font-semibold text-slate-900">{job.status}</dd>
            </div>
          </dl>
          {job.status === 'ERROR' && job.attempt_count < job.max_attempts && activeRole !== 'student' && (
            <button type="button" disabled={retrying} onClick={retry} className="inline-flex items-center gap-2 mt-6 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">
              <RotateCcw className="w-4 h-4" /> {retrying ? 'Retrying...' : 'Retry job'}
            </button>
          )}
        </section>
      )}
    </div>
  );
};
