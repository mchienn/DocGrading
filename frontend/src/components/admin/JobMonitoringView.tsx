import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Eye,
  Loader2,
  RefreshCw,
  RotateCw,
  X,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type JobStatus = components['schemas']['AnalysisJobStatus'];
const statuses: JobStatus[] = ['QUEUED', 'RUNNING', 'DONE', 'ERROR'];

const STATUS_BADGE_CLASS: Record<JobStatus, string> = {
  DONE: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  RUNNING: 'bg-sky-50 text-sky-700 border-sky-200',
  QUEUED: 'bg-amber-50 text-amber-700 border-amber-200',
  ERROR: 'bg-rose-50 text-rose-700 border-rose-200',
};

const JobDetail: React.FC<{ jobId: string; onClose: () => void }> = ({ jobId, onClose }) => {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const detail = useQuery({
    queryKey: ['admin-jobs', 'detail', jobId],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/operations/analysis-jobs/{job_id}', {
          params: { path: { job_id: jobId } },
        }),
      ),
  });

  const job = detail.data;

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby="job-detail-title"
      className="m-auto w-full max-w-xl rounded-xl border border-[#DDE2E8] p-5 sm:p-6 bg-white shadow-2xl backdrop:bg-slate-900/50"
    >
      <div className="flex items-center justify-between border-b border-slate-200 pb-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-[#1F4B7A]" />
          <h2 id="job-detail-title" className="font-bold text-base text-slate-900">
            Analysis Job Details
          </h2>
        </div>
        <button
          type="button"
          autoFocus
          onClick={onClose}
          className="p-1 text-slate-400 hover:text-slate-600 rounded-lg"
          aria-label="Close details modal"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {detail.isLoading && (
        <div className="p-8 text-center text-slate-400 flex flex-col items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-[#1F4B7A]" />
          <span className="text-xs">Loading job details...</span>
        </div>
      )}

      {detail.error && (
        <p role="alert" className="text-xs text-rose-700 mt-4 p-3 bg-rose-50 border border-rose-200 rounded-lg">
          {getErrorMessage(detail.error)}
        </p>
      )}

      {job && (
        <div className="mt-4 space-y-3 text-xs text-slate-700">
          <dl className="space-y-2.5 break-all divide-y divide-slate-100">
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Assignment</dt>
              <dd className="font-semibold text-slate-900 text-right">
                {job.assignment_title}
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Filename</dt>
              <dd className="text-slate-900 text-right">
                {job.filename}
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Student</dt>
              <dd className="text-right">
                <span className="font-medium text-slate-900">
                  {job.student_display_name}
                </span>
                <span className="text-slate-500 text-[11px] block">
                  {job.student_email}
                </span>
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Course</dt>
              <dd className="font-medium text-slate-900 text-right">
                {job.course_code} — {job.course_name}
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Status</dt>
              <dd>
                <span
                  className={`px-2 py-0.5 rounded font-semibold text-[10px] border ${STATUS_BADGE_CLASS[job.status]}`}
                >
                  {job.status}
                </span>
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Attempts</dt>
              <dd className="font-mono text-slate-900 text-right">
                {job.attempt_count} / {job.max_attempts}
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Queued Time</dt>
              <dd className="text-slate-900 text-right">{new Date(job.queued_at).toLocaleString()}</dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Started Time</dt>
              <dd className="text-slate-900 text-right">
                {job.started_at ? new Date(job.started_at).toLocaleString() : '—'}
              </dd>
            </div>
            <div className="pt-2 flex justify-between gap-2">
              <dt className="font-semibold text-slate-500 shrink-0">Finished Time</dt>
              <dd className="text-slate-900 text-right">
                {job.finished_at ? new Date(job.finished_at).toLocaleString() : '—'}
              </dd>
            </div>
            {job.status === 'ERROR' && (
              <>
                <div className="pt-2 flex justify-between gap-2">
                  <dt className="font-semibold text-rose-700 shrink-0">Error Code</dt>
                  <dd className="font-mono text-rose-800 text-right">{job.error_code ?? '—'}</dd>
                </div>
                <div className="pt-2">
                  <dt className="font-semibold text-rose-700 mb-1">Diagnostic Detail</dt>
                  <dd className="p-2.5 bg-rose-50 border border-rose-200 text-rose-800 rounded font-mono text-[11px] whitespace-pre-wrap">
                    {job.error_detail ?? 'No diagnostic detail available.'}
                  </dd>
                </div>
              </>
            )}
          </dl>

          <details className="mt-4 pt-3 border-t border-slate-200">
            <summary className="cursor-pointer font-semibold text-xs text-slate-500 hover:text-slate-700 select-none py-1">
              Technical details
            </summary>
            <div className="mt-2 p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1.5 font-mono text-[11px] text-slate-600 break-all">
              <div>Job ID: {job.id}</div>
              <div>Submission ID: {job.submission_id}</div>
              <div>Document Version ID: {job.document_version_id}</div>
              <div>Rubric Version ID: {job.rubric_version_id}</div>
              <div>Course ID: {job.course_id}</div>
              <div>Assignment ID: {job.assignment_id}</div>
            </div>
          </details>
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2 border-t border-slate-200 pt-3">
        <button
          type="button"
          disabled={detail.isFetching}
          onClick={() => void detail.refetch()}
          className="px-3 py-1.5 border border-[#DDE2E8] hover:bg-slate-50 rounded-lg text-xs font-semibold text-slate-700 disabled:opacity-40"
        >
          Refresh
        </button>
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-1.5 bg-[#1F4B7A] hover:bg-[#163657] text-white rounded-lg text-xs font-semibold"
        >
          Close
        </button>
      </div>
    </dialog>
  );
};

export const JobMonitoringView: React.FC = () => {
  const [status, setStatus] = useState<JobStatus | ''>('');
  const [courseId, setCourseId] = useState('');
  const [page, setPage] = useState(1);
  const [selectedJob, setSelectedJob] = useState<string>();
  const queryClient = useQueryClient();
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });

  // Operations dashboard summary for aggregate job status counts
  const dashboardQuery = useQuery({
    queryKey: ['admin-dashboard'],
    queryFn: () => apiData(api.GET('/api/v1/operations/dashboard')),
    refetchInterval: (query) => {
      const data = query.state.data;
      const active = (data?.jobs_by_status.QUEUED ?? 0) + (data?.jobs_by_status.RUNNING ?? 0);
      return active > 0 ? 5_000 : false;
    },
  });

  // Analysis jobs list
  const jobsQuery = useQuery({
    queryKey: ['admin-jobs', status, courseId, page],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/operations/analysis-jobs', {
          params: {
            query: {
              status: status || undefined,
              course_id: courseId || undefined,
              page,
              page_size: 25,
            },
          },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => job.status === 'QUEUED' || job.status === 'RUNNING')
        ? 5_000
        : false,
  });

  const retry = useMutation({
    mutationFn: (jobId: string) =>
      apiData(
        api.POST('/api/v1/operations/analysis-jobs/{job_id}/retry', {
          params: { path: { job_id: jobId } },
        }),
      ),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]),
  });

  const jobsData = jobsQuery.data;
  const dashboardData = dashboardQuery.data;

  const queuedTotal = dashboardData?.jobs_by_status.QUEUED ?? 0;
  const runningTotal = dashboardData?.jobs_by_status.RUNNING ?? 0;
  const doneTotal = dashboardData?.jobs_by_status.DONE ?? 0;
  const errorTotal = dashboardData?.jobs_by_status.ERROR ?? 0;
  const grandTotal = queuedTotal + runningTotal + doneTotal + errorTotal;

  const pages = Math.max(1, Math.ceil((jobsData?.total ?? 0) / 25));

  // Keep the page in range when the filtered total (and so the page count) shrinks.
  useEffect(() => {
    if (jobsData && page > pages) setPage(pages);
  }, [jobsData, page, pages]);

  const filterCards: Array<{
    value: JobStatus | '';
    label: string;
    count: number;
    color: string;
    bg: string;
  }> = [
    { value: '', label: 'ALL', count: grandTotal, color: 'text-slate-700', bg: 'bg-slate-100' },
    { value: 'QUEUED', label: 'QUEUED', count: queuedTotal, color: 'text-amber-700', bg: 'bg-amber-100' },
    { value: 'RUNNING', label: 'RUNNING', count: runningTotal, color: 'text-sky-700', bg: 'bg-sky-100' },
    { value: 'DONE', label: 'DONE', count: doneTotal, color: 'text-emerald-700', bg: 'bg-emerald-100' },
    { value: 'ERROR', label: 'ERROR', count: errorTotal, color: 'text-rose-700', bg: 'bg-rose-100' },
  ];

  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#DDE2E8] pb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Job Monitoring</h1>
          <p className="text-sm text-[#596579] mt-1">
            Real-time pipeline monitoring, queue status, and failure recovery.
          </p>
        </div>
        <button
          type="button"
          disabled={jobsQuery.isFetching || dashboardQuery.isFetching}
          onClick={() => {
            void jobsQuery.refetch();
            void dashboardQuery.refetch();
          }}
          className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#DDE2E8] bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 rounded-lg transition-colors disabled:opacity-50 shrink-0 self-start sm:self-auto"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${
              jobsQuery.isFetching || dashboardQuery.isFetching ? 'animate-spin' : ''
            }`}
          />
          <span>Refresh</span>
        </button>
      </div>

      <label className="block max-w-sm text-xs font-semibold text-slate-700">
        Course
        <select
          value={courseId}
          onChange={(event) => {
            setCourseId(event.target.value);
            setPage(1);
          }}
          className="mt-1.5 w-full rounded-lg border border-[#DDE2E8] bg-white px-3 py-2 text-sm font-normal text-slate-900"
        >
          <option value="">All courses</option>
          {coursesQuery.data?.map((course) => (
            <option key={course.id} value={course.id}>
              {course.code} — {course.name}
            </option>
          ))}
        </select>
      </label>

      {/* Status KPI Filter Buttons (platform-wide counts) */}
      <section aria-label="Status filters and summary" className="space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {filterCards.map((card) => {
            const isSelected = status === card.value;
            return (
              <button
                key={card.label}
                type="button"
                onClick={() => {
                  setStatus(card.value);
                  setPage(1);
                }}
                className={`p-3.5 rounded-xl border text-left transition-all ${
                  isSelected
                    ? 'border-[#1F4B7A] bg-[#EAF1F8] ring-2 ring-[#1F4B7A]/20'
                    : 'border-[#DDE2E8] bg-white hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-600">{card.label}</span>
                  {card.value === 'RUNNING' && runningTotal > 0 && (
                    <span className="w-2 h-2 rounded-full bg-sky-500 animate-pulse" />
                  )}
                </div>
                <p className="text-xl font-bold text-slate-900 mt-1 font-mono">
                  {dashboardQuery.isLoading ? '—' : card.count}
                </p>
              </button>
            );
          })}
        </div>

        {/* Compact Segmented Status Bar */}
        {grandTotal > 0 && (
          <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden flex" role="img" aria-label="Job status proportions">
            {doneTotal > 0 && (
              <div
                style={{ width: `${(doneTotal / grandTotal) * 100}%` }}
                className="bg-emerald-500 h-full"
                title={`DONE: ${doneTotal}`}
              />
            )}
            {runningTotal > 0 && (
              <div
                style={{ width: `${(runningTotal / grandTotal) * 100}%` }}
                className="bg-sky-500 h-full"
                title={`RUNNING: ${runningTotal}`}
              />
            )}
            {queuedTotal > 0 && (
              <div
                style={{ width: `${(queuedTotal / grandTotal) * 100}%` }}
                className="bg-amber-500 h-full"
                title={`QUEUED: ${queuedTotal}`}
              />
            )}
            {errorTotal > 0 && (
              <div
                style={{ width: `${(errorTotal / grandTotal) * 100}%` }}
                className="bg-rose-500 h-full"
                title={`ERROR: ${errorTotal}`}
              />
            )}
          </div>
        )}
        {courseId && (
          <p className="text-[11px] text-slate-500">
            Status counts above cover all courses; the table below is filtered to the selected course.
          </p>
        )}
      </section>

      {/* Alerts */}
      {(jobsQuery.error || dashboardQuery.error || coursesQuery.error || retry.error) && (
        <div role="alert" className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs">
          {getErrorMessage(
            retry.error ?? jobsQuery.error ?? dashboardQuery.error ?? coursesQuery.error,
          )}
        </div>
      )}

      {retry.isSuccess && (
        <div role="status" className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
          <span>Job queued for retry. Processing pipeline will re-evaluate submission.</span>
        </div>
      )}

      {/* Jobs Table */}
      <div className="bg-white border border-[#DDE2E8] rounded-xl overflow-hidden">
        {jobsQuery.isLoading ? (
          <div className="p-12 text-center text-slate-400 flex flex-col items-center gap-3">
            <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
            <span className="text-sm">Loading analysis jobs...</span>
          </div>
        ) : (jobsData?.items.length ?? 0) === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <Activity className="w-10 h-10 mx-auto mb-2 text-slate-300 stroke-1" />
            <p className="font-semibold text-slate-700 text-sm">No analysis jobs found</p>
            <p className="text-xs text-slate-400 mt-1">
              {courseId
                ? `No ${status ? `${status} ` : ''}jobs found for the selected course.`
                : status
                ? `No jobs currently in ${status} status.`
                : 'No analysis jobs have been submitted yet.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-[#F5F7FA] border-b border-[#DDE2E8] text-[#596579] font-semibold">
                <tr>
                  <th className="p-3.5">Assignment / File</th>
                  <th className="p-3.5">Student / Course</th>
                  <th className="p-3.5">Status</th>
                  <th className="p-3.5">Attempts</th>
                  <th className="p-3.5">Queued</th>
                  <th className="p-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobsData?.items.map((job) => {
                  return (
                    <tr key={job.id} className="hover:bg-slate-50 transition-colors">
                      <td className="p-3.5">
                        <p className="font-semibold text-slate-900 text-xs">{job.assignment_title}</p>
                        <p className="text-[11px] text-slate-500 truncate max-w-[200px]" title={job.filename}>
                          {job.filename}
                        </p>
                      </td>
                      <td className="p-3.5">
                        <p className="font-medium text-slate-900">{job.student_display_name}</p>
                        <p className="text-[11px] text-slate-500">
                          {job.course_code} · {job.student_email}
                        </p>
                      </td>
                      <td className="p-3.5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${STATUS_BADGE_CLASS[job.status]}`}
                        >
                          {job.status}
                        </span>
                      </td>
                      <td className="p-3.5 font-mono text-slate-700">
                        {job.attempt_count} / {job.max_attempts}
                      </td>
                      <td className="p-3.5 text-[#8893A5] whitespace-nowrap">
                        {new Date(job.queued_at).toLocaleString()}
                      </td>
                      <td className="p-3.5 text-right space-x-2 whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => setSelectedJob(job.id)}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 border border-[#DDE2E8] hover:bg-slate-100 text-slate-700 rounded-lg text-xs font-medium transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>Details</span>
                        </button>
                        {job.status === 'ERROR' && (
                          <button
                            type="button"
                            disabled={retry.isPending || job.attempt_count >= job.max_attempts}
                            onClick={() => retry.mutate(job.id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 bg-[#1F4B7A] hover:bg-[#163657] text-white rounded-lg text-xs font-semibold disabled:opacity-40 transition-colors"
                            title={
                              job.attempt_count >= job.max_attempts
                                ? 'Max retry attempts exceeded'
                                : 'Queue job for re-execution'
                            }
                          >
                            <RotateCw className="w-3.5 h-3.5" />
                            <span>Retry</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {!jobsQuery.isLoading && !jobsQuery.isError && (jobsData?.total ?? 0) > 0 && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-[#596579]">
          <span>
            {jobsData?.total ?? 0} jobs · Page {page} of {pages}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Previous page"
              disabled={page <= 1 || jobsQuery.isFetching}
              onClick={() => setPage(page - 1)}
              className="px-3 py-1.5 border border-[#DDE2E8] bg-white rounded-lg font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              Previous
            </button>
            <button
              type="button"
              aria-label="Next page"
              disabled={page >= pages || jobsQuery.isFetching}
              onClick={() => setPage(page + 1)}
              className="px-3 py-1.5 border border-[#DDE2E8] bg-white rounded-lg font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {selectedJob && (
        <JobDetail jobId={selectedJob} onClose={() => setSelectedJob(undefined)} />
      )}
    </div>
  );
};
