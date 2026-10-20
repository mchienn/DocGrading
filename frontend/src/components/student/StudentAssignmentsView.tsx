import React from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { Bell, CalendarClock, FileUp, KeyRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api, apiData, getErrorMessage } from '../../api/client';

export const StudentAssignmentsView: React.FC = () => {
  const navigate = useNavigate();
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });
  const courses = coursesQuery.data ?? [];
  const assignmentQueries = useQueries({
    queries: courses.map((course) => ({
      queryKey: ['assignments', course.id],
      queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/assignments', {
        params: { path: { course_id: course.id } },
      })),
    })),
  });
  const announcementQueries = useQueries({
    queries: courses.map((course) => ({
      queryKey: ['announcements', course.id],
      queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/announcements', {
        params: { path: { course_id: course.id } },
      })),
    })),
  });
  const rows = courses.flatMap((course, index) =>
    (assignmentQueries[index]?.data ?? []).map((assignment) => ({ course, assignment })),
  );
  const announcementRows = courses.flatMap((course, index) =>
    (announcementQueries[index]?.data ?? []).map((announcement) => ({ course, announcement })),
  );
  const [now, setNow] = React.useState(Date.now());
  const nextDeadline = rows.reduce((nearest, { assignment }) => {
    const deadline = new Date(assignment.due_at).getTime();
    return assignment.status === 'OPEN' && deadline > now
      ? Math.min(nearest, deadline)
      : nearest;
  }, Number.POSITIVE_INFINITY);
  React.useEffect(() => {
    if (!Number.isFinite(nextDeadline)) return;
    const timeout = window.setTimeout(
      () => setNow(Date.now()),
      Math.min(nextDeadline - now + 50, 2_147_483_647),
    );
    return () => window.clearTimeout(timeout);
  }, [nextDeadline, now]);
  const error = coursesQuery.error
    ?? assignmentQueries.find((query) => query.error)?.error
    ?? announcementQueries.find((query) => query.error)?.error;
  const loading = coursesQuery.isLoading
    || assignmentQueries.some((query) => query.isLoading)
    || announcementQueries.some((query) => query.isLoading);

  return (
    <div className="p-6 sm:p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Assignments</h1>
          <p className="text-sm text-slate-500 mt-1">Open and closed assignments from enrolled courses.</p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/student/join')}
          className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] hover:bg-[#183B60] text-white rounded-lg text-sm font-semibold shrink-0 shadow-sm"
        >
          <KeyRound className="w-4 h-4" /> Join course
        </button>
      </div>

      {error && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {getErrorMessage(error)}
        </div>
      )}

      {!loading && courses.length > 0 && (
        <details className="bg-white border border-slate-200 rounded-xl">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">
            Course information ({courses.length})
          </summary>
          <div className="grid gap-3 border-t border-slate-200 p-4 sm:grid-cols-2">
            {courses.map((course) => (
              <article key={course.id} className="rounded-lg bg-slate-50 p-3">
                <p className="font-semibold text-slate-900">
                  <span className="font-mono text-xs text-sky-700">{course.code}</span>
                  <span className="ml-2">{course.name}</span>
                </p>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                  <dt className="text-slate-500">Instructor</dt>
                  <dd className="text-slate-700">
                    {course.owner.display_name}
                    {' · '}
                    <a className="hover:underline" href={`mailto:${course.owner.email}`}>{course.owner.email}</a>
                  </dd>
                  <dt className="text-slate-500">Term</dt>
                  <dd className="text-slate-700">{course.term}</dd>
                  <dt className="text-slate-500">Status</dt>
                  <dd className="text-slate-700">{course.status}</dd>
                </dl>
              </article>
            ))}
          </div>
        </details>
      )}

      {!loading && announcementRows.length > 0 && (
        <section aria-labelledby="student-announcements-title" className="space-y-3">
          <h2 id="student-announcements-title" className="text-base font-bold text-slate-900">Course announcements</h2>
          {announcementRows.map(({ course, announcement }) => (
            <article key={announcement.id} className="bg-sky-50 border border-sky-200 rounded-xl p-4">
              <div className="flex items-center gap-2 text-xs font-bold text-sky-800">
                <Bell className="w-4 h-4" /> {course.code} · {announcement.title}
              </div>
              <p className="text-sm text-slate-700 mt-2 whitespace-pre-wrap">{announcement.body}</p>
              <p className="text-xs text-slate-500 mt-2">{new Date(announcement.updated_at).toLocaleString()}</p>
            </article>
          ))}
        </section>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading assignments...</p>
      ) : rows.length === 0 ? (
        <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No visible assignments.</p>
      ) : (
        <div className="space-y-3">
          {rows.map(({ course, assignment }) => {
            const attemptsUsed = assignment.student_attempts_used ?? 0;
            const limitReached = attemptsUsed >= assignment.max_submissions;
            const canUpload = assignment.status === 'OPEN'
              && new Date(assignment.due_at).getTime() > now
              && !limitReached;
            return (
              <article key={assignment.id} className="bg-white border border-slate-200 rounded-xl p-5">
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>
                      <span className="text-xs font-medium text-slate-600">{course.name}</span>
                      <span className="text-[11px] font-semibold px-2 py-0.5 rounded border bg-slate-50 text-slate-600 border-slate-200">{assignment.status}</span>
                    </div>
                    <h2 className="font-bold text-slate-900 mt-2">{assignment.title}</h2>
                    {assignment.description && <p className="text-sm text-slate-600 mt-1">{assignment.description}</p>}
                    <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
                      <CalendarClock className="w-3.5 h-3.5" /> Due {new Date(assignment.due_at).toLocaleString()}
                    </p>
                    <p className={`text-xs font-semibold mt-2 ${limitReached ? 'text-amber-700' : 'text-slate-600'}`}>
                      Attempts used: {attemptsUsed}/{assignment.max_submissions}
                    </p>
                  </div>
                  {canUpload && (
                    <button
                      type="button"
                      onClick={() => navigate(`/student/assignments/${course.id}/${assignment.id}/upload`)}
                      className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold shrink-0"
                    >
                      <FileUp className="w-4 h-4" /> Upload PDF
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
};
