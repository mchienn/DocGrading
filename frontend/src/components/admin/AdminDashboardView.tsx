import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';

export const AdminDashboardView: React.FC = () => {
  const dashboard = useQuery({
    queryKey: ['admin-dashboard'],
    queryFn: () => apiData(api.GET('/api/v1/operations/dashboard')),
  });
  const users = useQuery({
    queryKey: ['admin-users', 'total'],
    queryFn: () => apiData(api.GET('/api/v1/users', { params: { query: { page_size: 1 } } })),
  });
  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex justify-between border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Admin dashboard</h1>
        <button type="button" disabled={dashboard.isFetching || users.isFetching} onClick={() => { void dashboard.refetch(); void users.refetch(); }} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Refresh</button>
      </div>
      <nav aria-label="Administration" className="flex gap-4 text-sm text-sky-700 underline">
        <Link to="/admin/users">Users</Link><Link to="/admin/jobs">Analysis jobs</Link><Link to="/admin/audit">Audit trail</Link>
      </nav>
      {(dashboard.error || users.error) && <p role="alert" className="text-rose-700">{getErrorMessage(dashboard.error ?? users.error)}</p>}
      {(dashboard.isLoading || users.isLoading) && <p role="status">Loading dashboard...</p>}
      <div className="grid sm:grid-cols-3 gap-4">
        <div className="p-5 bg-white border border-slate-200 rounded-xl"><h2>Total users</h2><p className="text-2xl font-bold">{users.data?.total ?? '—'}</p></div>
        <div className="p-5 bg-white border border-slate-200 rounded-xl"><h2>Queued jobs</h2><p className="text-2xl font-bold">{dashboard.data?.jobs_by_status.QUEUED ?? '—'}</p></div>
        <div className="p-5 bg-white border border-slate-200 rounded-xl"><h2>Open review requests</h2><p className="text-2xl font-bold">{dashboard.data?.open_review_requests ?? '—'}</p></div>
      </div>
      {dashboard.data && <>
        <section className="p-5 bg-white border border-slate-200 rounded-xl space-y-3">
          <h2 className="font-bold">Analysis jobs by status</h2>
          <dl className="flex flex-wrap gap-6">{Object.entries(dashboard.data.jobs_by_status).map(([status, count]) => <div key={status}><dt className="text-xs text-slate-500">{status}</dt><dd className="text-xl font-semibold">{count}</dd></div>)}</dl>
        </section>
        <section className="p-5 bg-white border border-slate-200 rounded-xl space-y-3">
          <h2 className="font-bold">Submissions by course</h2>
          {!dashboard.data.submissions_by_course.length && <p>No courses available.</p>}
          {dashboard.data.submissions_by_course.map((course) => <div key={course.course_id} className="flex justify-between border-b border-slate-200 py-2 gap-4"><Link className="text-sky-700 underline" to={`/admin/courses/${course.course_id}/submissions`}>{course.course_code} — {course.course_name}</Link><span>{course.submission_count}</span></div>)}
        </section>
      </>}
    </div>
  );
};
