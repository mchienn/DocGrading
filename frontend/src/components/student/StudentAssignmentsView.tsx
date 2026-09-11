import React from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { CalendarClock, FileUp } from 'lucide-react';
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
  const rows = courses.flatMap((course, index) =>
    (assignmentQueries[index]?.data ?? []).map((assignment) => ({ course, assignment })),
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
  const error = coursesQuery.error ?? assignmentQueries.find((query) => query.error)?.error;
  const loading = coursesQuery.isLoading || assignmentQueries.some((query) => query.isLoading);

  return (
    <div className="p-6 sm:p-8 max-w-5xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-2xl font-bold text-slate-900">Assignments</h1>
        <p className="text-sm text-slate-500 mt-1">Open and closed assignments from enrolled courses.</p>
      </div>

      {error && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {getErrorMessage(error)}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading assignments...</p>
      ) : rows.length === 0 ? (
        <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No visible assignments.</p>
      ) : (
        <div className="space-y-3">
          {rows.map(({ course, assignment }) => (
            <article key={assignment.id} className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded border bg-slate-50 text-slate-600 border-slate-200">{assignment.status}</span>
                  </div>
                  <h2 className="font-bold text-slate-900 mt-2">{assignment.title}</h2>
                  {assignment.description && <p className="text-sm text-slate-600 mt-1">{assignment.description}</p>}
                  <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
                    <CalendarClock className="w-3.5 h-3.5" /> Due {new Date(assignment.due_at).toLocaleString()}
                  </p>
                </div>
                {assignment.status === 'OPEN' && new Date(assignment.due_at).getTime() > now && (
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
          ))}
        </div>
      )}
    </div>
  );
};
