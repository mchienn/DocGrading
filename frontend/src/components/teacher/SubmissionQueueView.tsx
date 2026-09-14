import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ChevronLeft, ChevronRight, FileCheck2, LockKeyhole } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { api, apiData, getErrorMessage } from '../../api/client';

type QueueStatus = components['schemas']['QueueStatus'];
type QueueSort = components['schemas']['QueueSort'];

interface SubmissionQueueViewProps {
  role: 'teacher' | 'admin';
}

const queueStatuses: QueueStatus[] = ['UNREVIEWED', 'REVIEWED', 'ERROR'];

export const SubmissionQueueView: React.FC<SubmissionQueueViewProps> = ({ role }) => {
  const { courseId = '' } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<QueueStatus | ''>('');
  const [sort, setSort] = useState<QueueSort>('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const queueQuery = useQuery({
    queryKey: ['submission-queue', courseId, status, sort, page, pageSize],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/submission-queue', {
      params: {
        path: { course_id: courseId },
        query: { status: status || undefined, sort, page, page_size: pageSize },
      },
    })),
    enabled: Boolean(courseId),
  });

  const queue = queueQuery.data;
  const totalPages = Math.max(1, Math.ceil((queue?.total ?? 0) / pageSize));

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6">
      <button
        type="button"
        onClick={() => navigate(`/${role}/courses/${courseId}`)}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to course
      </button>

      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Submission Queue</h1>
        <p className="text-sm text-slate-500 mt-1 font-mono break-all">Course {courseId}</p>
      </div>

      <section aria-label="Queue controls" className="bg-white border border-slate-200 rounded-xl p-4 flex flex-wrap gap-4">
        <label className="text-sm text-slate-700">
          Queue status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as QueueStatus | '');
              setPage(1);
            }}
            className="block mt-1 px-3 py-2 border border-slate-300 rounded-lg bg-white"
          >
            <option value="">ALL</option>
            {queueStatuses.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-sm text-slate-700">
          Submitted time
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as QueueSort);
              setPage(1);
            }}
            className="block mt-1 px-3 py-2 border border-slate-300 rounded-lg bg-white"
          >
            <option value="desc">Newest first</option>
            <option value="asc">Oldest first</option>
          </select>
        </label>
        <label className="text-sm text-slate-700">
          Page size
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
            className="block mt-1 px-3 py-2 border border-slate-300 rounded-lg bg-white"
          >
            {[10, 25, 50, 100].map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
      </section>

      {queueQuery.error && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm flex items-center justify-between gap-3">
          <span>{getErrorMessage(queueQuery.error)}</span>
          <button
            type="button"
            disabled={queueQuery.isFetching}
            onClick={() => void queueQuery.refetch()}
            className="font-semibold underline disabled:opacity-40"
          >
            {queueQuery.isFetching ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 border-b border-slate-200 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3">Student ID</th>
                <th className="px-4 py-3">Submitted</th>
                <th className="px-4 py-3">Document status</th>
                <th className="px-4 py-3">Queue status</th>
                <th className="px-4 py-3">Review lock</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {queueQuery.error && !queue ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Queue unavailable.</td></tr>
              ) : queueQuery.isLoading ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Loading queue...</td></tr>
              ) : !queue?.items.length ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">No submissions match this API filter.</td></tr>
              ) : queue.items.map((item) => (
                <tr key={item.submission_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs break-all">{item.student_id}</td>
                  <td className="px-4 py-3 whitespace-nowrap">{new Date(item.submitted_at).toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono text-xs">{item.document_status ?? 'NO_DOCUMENT'}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex px-2 py-1 rounded border border-slate-200 bg-slate-50 font-mono text-xs">
                      {item.queue_status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {item.review_lock ? (
                      <span className="inline-flex items-center gap-1.5" title={`Expires ${new Date(item.review_lock.expires_at).toLocaleString()}`}>
                        <LockKeyhole className="w-3.5 h-3.5" /> {item.review_lock.reviewer_display_name}
                      </span>
                    ) : 'Unlocked'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      disabled={!item.document_version_id || !['AWAITING_REVIEW', 'APPROVED', 'PUBLISHED'].includes(item.document_status ?? '')}
                      onClick={() => navigate(
                        `/${role}/courses/${courseId}/submissions/${item.submission_id}`,
                        { state: { documentStatus: item.document_status } },
                      )}
                      className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-900 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
                    >
                      <FileCheck2 className="w-3.5 h-3.5" /> Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>{queue?.total ?? 0} submissions · page {queue?.page ?? page} of {totalPages}</span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1 || queueQuery.isFetching}
            onClick={() => setPage((value) => value - 1)}
            className="p-2 border border-slate-300 rounded-lg disabled:opacity-40"
            aria-label="Previous page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            disabled={page >= totalPages || queueQuery.isFetching}
            onClick={() => setPage((value) => value + 1)}
            className="p-2 border border-slate-300 rounded-lg disabled:opacity-40"
            aria-label="Next page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
