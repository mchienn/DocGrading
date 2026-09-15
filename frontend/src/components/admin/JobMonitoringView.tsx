import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type JobStatus = components['schemas']['AnalysisJobStatus'];
const statuses: JobStatus[] = ['QUEUED', 'RUNNING', 'DONE', 'ERROR'];

const JobDetail: React.FC<{ jobId: string; onClose: () => void }> = ({ jobId, onClose }) => {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const detail = useQuery({
    queryKey: ['admin-jobs', 'detail', jobId],
    queryFn: () => apiData(api.GET('/api/v1/operations/analysis-jobs/{job_id}', { params: { path: { job_id: jobId } } })),
  });
  const job = detail.data;
  return <dialog ref={dialog} onClose={onClose} aria-labelledby="job-detail-title" className="m-auto w-full max-w-xl rounded-xl border border-slate-200 p-5 backdrop:bg-slate-900/50">
    <div className="flex justify-between gap-3"><h2 id="job-detail-title" className="font-bold">Analysis job details</h2><button autoFocus type="button" onClick={onClose} className="px-3 py-2 border border-slate-200 rounded-lg">Close</button></div>
    {detail.isLoading && <p role="status">Loading job...</p>}
    {detail.error && <p role="alert" className="text-rose-700">{getErrorMessage(detail.error)}</p>}
    {job && <dl className="mt-4 space-y-3 text-sm break-all">
      <div><dt className="font-semibold">Job ID</dt><dd>{job.id}</dd></div>
      <div><dt className="font-semibold">Course</dt><dd>{job.course_code} — {job.course_name}</dd></div>
      <div><dt className="font-semibold">Submission ID</dt><dd>{job.submission_id}</dd></div>
      <div><dt className="font-semibold">Status</dt><dd>{job.status}</dd></div>
      <div><dt className="font-semibold">Attempts</dt><dd>{job.attempt_count} / {job.max_attempts}</dd></div>
      <div><dt className="font-semibold">Queued</dt><dd>{new Date(job.queued_at).toLocaleString()}</dd></div>
      <div><dt className="font-semibold">Started</dt><dd>{job.started_at ? new Date(job.started_at).toLocaleString() : '—'}</dd></div>
      <div><dt className="font-semibold">Finished</dt><dd>{job.finished_at ? new Date(job.finished_at).toLocaleString() : '—'}</dd></div>
      {job.status === 'ERROR' && <p className="text-rose-700">Analysis failed. You can retry this job from the list.</p>}
    </dl>}
    <button type="button" disabled={detail.isFetching} onClick={() => void detail.refetch()} className="mt-4 px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Refresh details</button>
  </dialog>;
};

export const JobMonitoringView: React.FC = () => {
  const [status, setStatus] = useState<JobStatus | ''>('');
  const [page, setPage] = useState(1);
  const [selectedJob, setSelectedJob] = useState<string>();
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ['admin-jobs', status, page],
    queryFn: () => apiData(api.GET('/api/v1/operations/analysis-jobs', { params: { query: { status: status || undefined, page, page_size: 25 } } })),
  });
  const retry = useMutation({
    mutationFn: (jobId: string) => apiData(api.POST('/api/v1/operations/analysis-jobs/{job_id}/retry', { params: { path: { job_id: jobId } } })),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ['admin-jobs'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
    ]),
  });
  const pages = Math.max(1, Math.ceil((jobs.data?.total ?? 0) / 25));
  return <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
    <h1 className="text-2xl font-bold border-b border-slate-200 pb-5">Analysis jobs</h1>
    <section aria-label="Job filters" className="flex gap-4 p-4 bg-white border border-slate-200 rounded-xl">
      <label className="text-sm">Status<select value={status} onChange={(event) => { setStatus(event.target.value as JobStatus | ''); setPage(1); }} className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg"><option value="">ALL</option>{statuses.map((value) => <option key={value}>{value}</option>)}</select></label>
      <button type="button" disabled={jobs.isFetching} onClick={() => void jobs.refetch()} className="self-end px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Refresh</button>
    </section>
    {(jobs.error || retry.error) && <p role="alert" className="text-rose-700">{getErrorMessage(retry.error ?? jobs.error)}</p>}
    {retry.isSuccess && <p role="status" className="text-emerald-700">Job queued for retry.</p>}
    {jobs.isLoading && <p role="status">Loading jobs...</p>}
    <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto"><table className="w-full text-sm text-left"><thead className="bg-slate-50"><tr>{['Job / Course', 'Status', 'Attempts', 'Queued', 'Actions'].map((label) => <th key={label} className="p-4">{label}</th>)}</tr></thead><tbody>
      {jobs.data?.items.map((job) => <tr key={job.id} className="border-t border-slate-200"><td className="p-4"><p className="font-mono text-xs">{job.id}</p><p>{job.course_code} — {job.course_name}</p></td><td className="p-4">{job.status}</td><td className="p-4">{job.attempt_count} / {job.max_attempts}</td><td className="p-4">{new Date(job.queued_at).toLocaleString()}</td><td className="p-4 space-x-2"><button type="button" onClick={() => setSelectedJob(job.id)} className="px-3 py-2 border border-slate-200 rounded-lg">Details</button>{job.status === 'ERROR' && <button type="button" disabled={retry.isPending} onClick={() => retry.mutate(job.id)} className="px-3 py-2 bg-slate-900 text-white rounded-lg disabled:opacity-40">{retry.isPending && retry.variables === job.id ? 'Retrying...' : 'Retry'}</button>}</td></tr>)}
      {jobs.data?.items.length === 0 && <tr><td colSpan={5} className="p-8 text-center text-slate-500">No jobs match this filter.</td></tr>}
    </tbody></table></div>
    <div className="flex justify-between text-sm"><span>{jobs.data?.total ?? '—'} jobs · page {page} of {pages}</span><div className="flex gap-2"><button type="button" aria-label="Previous page" disabled={page <= 1 || jobs.isFetching} onClick={() => setPage(page - 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Previous</button><button type="button" aria-label="Next page" disabled={page >= pages || jobs.isFetching} onClick={() => setPage(page + 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Next</button></div></div>
    {selectedJob && <JobDetail jobId={selectedJob} onClose={() => setSelectedJob(undefined)} />}
  </div>;
};
