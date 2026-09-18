import React, { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, ArrowLeft, CheckCircle2, Clock3, Eye, LoaderCircle, RotateCcw } from 'lucide-react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { WorkspaceRole } from '../../types/api';
import { PdfMarkerViewer, type PdfMarker } from '../teacher/PdfEvidenceViewer';

interface StudentStatusTimelineViewProps {
  activeRole: WorkspaceRole;
}

const friendlyErrors: Record<string, string> = {
  NOT_A_PDF: 'Uploaded file is not a PDF.',
  PDF_ENCRYPTED: 'Encrypted PDFs are not supported.',
  PDF_TOO_LARGE: 'PDF exceeds file-size limits.',
  PDF_DECODED_TOO_LARGE: 'Decoded PDF content exceeds processing limits.',
  PDF_PAGE_LIMIT: 'PDF exceeds page-count limits.',
  PDF_ACTIVE_CONTENT: 'This PDF contains an unsafe action or attachment. Review the evidence below, remove it, then export a clean PDF.',
  PDF_SCAN_ONLY: 'PDF needs a usable text layer; scanned documents are not supported.',
  PDF_SCAN_ANALYSIS_UNSUPPORTED: 'DocGrading could not safely verify a low-text page. Export a searchable PDF and upload it again.',
  PDF_MALFORMED: 'PDF structure is invalid or unsupported.',
  PDF_STORAGE_ERROR: 'Storage is temporarily unavailable.',
  PDF_IR_EXTRACTION_FAILED: 'Document extraction failed. Retry later or contact support.',
  FILE_INTEGRITY_EVALUATION_FAILED: 'File-integrity evaluation failed. Retry later or contact support.',
};

const diagnosticTitles: Record<string, string> = {
  NOT_A_PDF: 'Invalid PDF signature',
  PDF_TOO_LARGE: 'File is too large',
  PDF_ENCRYPTED: 'Encrypted PDF',
  PDF_PAGE_LIMIT: 'Too many pages',
  PDF_DECODED_TOO_LARGE: 'Processing budget exceeded',
  PDF_STRUCTURE_UNRECOVERABLE: 'PDF structure cannot be recovered',
  PDF_STRUCTURE_RECOVERED: 'Non-standard PDF structure recovered',
  PDF_ACTIVE_JAVASCRIPT: 'JavaScript action found',
  PDF_ACTIVE_LAUNCH: 'Launch action found',
  PDF_ACTIVE_FORM: 'Interactive form found',
  PDF_ACTIVE_MEDIA: 'Active media found',
  PDF_ACTIVE_REMOTE_ACTION: 'Unsafe remote action found',
  PDF_ACTIVE_AUTOMATIC_ACTION: 'Automatic action found',
  PDF_EMBEDDED_FILE: 'Embedded attachment found',
  PDF_SCAN_DETECTED: 'Scanned page detected',
  PDF_SCAN_ANALYSIS_UNSUPPORTED: 'Low-text page could not be verified',
  PDF_TEXT_LAYER_MISSING: 'Text layer missing',
  PDF_IR_EXTRACTION_FAILED: 'Document extraction failed',
  PDF_STORAGE_ERROR: 'Storage read failed',
  PDF_LINK_TARGET_MISMATCH: 'Link label and target differ',
  PDF_LINK_TARGET_UNVERIFIED: 'Link target needs review',
  FILE_INTEGRITY_EVALUATION_FAILED: 'File-integrity evaluation failed',
};

const diagnosticActions: Record<string, string> = {
  'pdf.choose_pdf': 'Choose a PDF file.',
  'pdf.reduce_size': 'Reduce the file size and upload it again.',
  'pdf.remove_password': 'Remove the password or encryption, then export again.',
  'pdf.reduce_pages': 'Reduce the page count.',
  'pdf.export_clean_copy': 'Use Export or Print to PDF to create a clean copy.',
  'pdf.remove_active_content': 'Remove scripts or actions, then export a clean copy.',
  'pdf.flatten_form': 'Flatten the form or print it to PDF.',
  'pdf.remove_attachments': 'Remove embedded attachments.',
  'pdf.run_ocr': 'Run OCR and export a searchable PDF.',
  'pdf.export_searchable_copy': 'Export a searchable PDF with a usable text layer.',
  'pdf.retry_or_contact_support': 'Retry later or contact support with the job ID.',
  'pdf.review_link_target': 'Review the visible link label and destination.',
};

export const StudentStatusTimelineView: React.FC<StudentStatusTimelineViewProps> = ({ activeRole }) => {
  const { jobId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const submissionId = searchParams.get('submissionId');
  const reused = searchParams.get('reused') === 'true';
  const queryClient = useQueryClient();
  const [retryError, setRetryError] = useState<string>();
  const [retrying, setRetrying] = useState(false);
  const [selectedMarkerId, setSelectedMarkerId] = useState<string>();

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
  const isTerminal = job?.status === 'DONE' || job?.status === 'ERROR';
  const reportQuery = useQuery({
    queryKey: ['document-validation-report', job?.document_version_id],
    queryFn: () => apiData(api.GET('/api/v1/document-versions/{version_id}/validation-report', {
      params: { path: { version_id: job?.document_version_id ?? '' } },
    })),
    enabled: Boolean(job?.document_version_id && isTerminal),
    retry: false,
  });
  const diagnostics = isTerminal ? (reportQuery.data?.diagnostics ?? []) : [];
  const diagnosticMarkers = useMemo<PdfMarker[]>(
    () => diagnostics.flatMap((diagnostic, index) => (
      diagnostic.page_number
        ? [{
            id: `${diagnostic.code}-${index}`,
            label: String(index + 1),
            pageNumber: diagnostic.page_number,
            bbox: diagnostic.bbox ?? undefined,
          }]
        : []
    )),
    [diagnostics],
  );

  const retry = async () => {
    if (!job) return;
    setRetrying(true);
    setRetryError(undefined);
    try {
      await apiData(api.POST('/api/v1/analysis-jobs/{job_id}/retry', {
        params: { path: { job_id: job.id } },
      }));
      setSelectedMarkerId(undefined);
      queryClient.removeQueries({
        queryKey: ['document-validation-report', job.document_version_id],
      });
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
      return reused
        ? {
            icon: <CheckCircle2 className="w-10 h-10 text-emerald-600" />,
            title: 'This PDF was already submitted',
            detail: 'No new upload was created. Showing the previous processing result.',
          }
        : {
            icon: <CheckCircle2 className="w-10 h-10 text-emerald-600" />,
            title: 'PDF processing completed',
            detail: 'Ingestion and validation finished. Teacher review and publication may still be pending.',
          };
    }
    if (job.status === 'ERROR') {
      const detail = job.error_code
        ? friendlyErrors[job.error_code] ?? 'PDF processing failed. Contact support with job ID.'
        : 'PDF processing failed. Contact support with job ID.';
      const isValidationError = !['PDF_STORAGE_ERROR', 'PDF_IR_EXTRACTION_FAILED', 'FILE_INTEGRITY_EVALUATION_FAILED'].includes(job.error_code ?? '');
      return {
        icon: <AlertCircle className="w-10 h-10 text-rose-600" />,
        title: reused
          ? 'This exact PDF was already rejected'
          : isValidationError
            ? 'PDF rejected'
            : 'Processing failed',
        detail: reused
          ? `This exact PDF was submitted before, so DocGrading did not upload or process it again. Previous result: ${detail}`
          : detail,
      };
    }
    if (job.status === 'RUNNING') {
      return reused
        ? {
            icon: <LoaderCircle className="w-10 h-10 text-sky-600 animate-spin" />,
            title: 'This PDF is already processing',
            detail: 'No new upload was created. Showing the existing processing job.',
          }
        : {
            icon: <LoaderCircle className="w-10 h-10 text-sky-600 animate-spin" />,
            title: 'Processing PDF',
            detail: 'DocGrading is validating and extracting the uploaded document.',
          };
    }
    return reused
      ? {
          icon: <Clock3 className="w-10 h-10 text-amber-600" />,
          title: 'This PDF is already queued',
          detail: 'No new upload was created. Showing the existing processing job.',
        }
      : {
          icon: <Clock3 className="w-10 h-10 text-amber-600" />,
          title: 'Queued',
          detail: 'Upload completed. Processing will start shortly.',
        };
  };
  const content = statusContent();

  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
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
          {job.status === 'DONE' && activeRole === 'student' && submissionId && (
            <button
              type="button"
              onClick={() => navigate(`/student/submissions/${submissionId}/result`)}
              className="inline-flex items-center gap-2 mt-6 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold"
            >
              <Eye className="w-4 h-4" /> View published result
            </button>
          )}
          {job.status === 'ERROR' && job.attempt_count < job.max_attempts && activeRole !== 'student' && (
            <button type="button" disabled={retrying} onClick={retry} className="inline-flex items-center gap-2 mt-6 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-50">
              <RotateCcw className="w-4 h-4" /> {retrying ? 'Retrying...' : 'Retry job'}
            </button>
          )}
        </section>
      )}
      {diagnostics.length > 0 && (
        <section className="space-y-3" aria-label="PDF validation evidence">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Validation evidence</h2>
            <p className="text-sm text-slate-600">
              Exact checks reported by the PDF processor. Page markers appear only when coordinates are available.
            </p>
          </div>
          {diagnostics.map((diagnostic, index) => {
            const markerId = diagnostic.page_number
              ? `${diagnostic.code}-${index}`
              : undefined;
            return (
              <article
                key={`${diagnostic.code}-${index}`}
                className={`rounded-xl border p-4 ${
                  diagnostic.disposition === 'BLOCK'
                    ? 'border-rose-200 bg-rose-50'
                    : diagnostic.disposition === 'WARN'
                      ? 'border-amber-200 bg-amber-50'
                      : 'border-slate-200 bg-white'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-mono font-semibold text-slate-500">{diagnostic.code}</p>
                    <h3 className="font-bold text-slate-900">
                      {diagnosticTitles[diagnostic.code] ?? 'PDF validation diagnostic'}
                    </h3>
                    {diagnostic.page_number && (
                      <p className="text-sm text-slate-600">Page {diagnostic.page_number}</p>
                    )}
                  </div>
                  <span className="rounded-full bg-white/80 px-2 py-1 text-xs font-bold text-slate-700">
                    {diagnostic.disposition}
                  </span>
                </div>
                {Object.keys(diagnostic.metrics).length > 0 && (
                  <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                    {Object.entries(diagnostic.metrics).map(([name, value]) => (
                      <div key={name} className="rounded-lg bg-white/70 p-2">
                        <dt className="text-xs text-slate-500">{name.replaceAll('_', ' ')}</dt>
                        <dd className="text-sm font-semibold text-slate-900">{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {diagnostic.action_key && diagnosticActions[diagnostic.action_key] && (
                  <p className="mt-3 text-sm font-medium text-slate-700">
                    {diagnosticActions[diagnostic.action_key]}
                  </p>
                )}
                {markerId && (
                  <button
                    type="button"
                    onClick={() => setSelectedMarkerId(markerId)}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white"
                  >
                    <Eye className="h-4 w-4" /> Open evidence
                  </button>
                )}
              </article>
            );
          })}
        </section>
      )}

      {job && selectedMarkerId && diagnosticMarkers.length > 0 && (
        <PdfMarkerViewer
          documentVersionId={job.document_version_id}
          markers={diagnosticMarkers}
          selectedMarkerId={selectedMarkerId}
          onSelectMarker={setSelectedMarkerId}
          ariaLabel="PDF validation evidence viewer"
        />
      )}
    </div>
  );
};
