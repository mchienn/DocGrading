import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart2,
  Clock,
  FileCheck,
  FolderOpen,
  Loader2,
  MessageSquare,
  RefreshCw,
  Table,
  Users,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type CourseSubmission = components['schemas']['CourseSubmissionCount'];
type TrendPoint = components['schemas']['AdminJobTrendPoint'];

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '0s';
  const rounded = Math.round(seconds);
  if (rounded < 60) return `${rounded}s`;
  const mins = Math.floor(rounded / 60);
  const remSecs = rounded % 60;
  return `${mins}m ${remSecs}s`;
}

export const AdminDashboardView: React.FC = () => {
  const [showTrendTable, setShowTrendTable] = useState(false);
  const [showStatusTable, setShowStatusTable] = useState(false);

  const dashboardQuery = useQuery({
    queryKey: ['admin-dashboard'],
    queryFn: () => apiData(api.GET('/api/v1/operations/dashboard')),
    refetchInterval: (query) => {
      const data = query.state.data;
      const active = (data?.jobs_by_status.QUEUED ?? 0) + (data?.jobs_by_status.RUNNING ?? 0);
      return active > 0 ? 5_000 : false;
    },
  });

  const data = dashboardQuery.data;

  // Status breakdown calculations
  const queuedCount = data?.jobs_by_status.QUEUED ?? 0;
  const runningCount = data?.jobs_by_status.RUNNING ?? 0;
  const doneCount = data?.jobs_by_status.DONE ?? 0;
  const errorCount = data?.jobs_by_status.ERROR ?? 0;
  const totalJobs = queuedCount + runningCount + doneCount + errorCount;

  const statusItems: Array<{ status: string; count: number; bg: string; text: string }> = [
    { status: 'DONE', count: doneCount, bg: 'bg-emerald-500', text: 'text-emerald-700' },
    { status: 'RUNNING', count: runningCount, bg: 'bg-sky-500', text: 'text-sky-700' },
    { status: 'QUEUED', count: queuedCount, bg: 'bg-amber-500', text: 'text-amber-700' },
    { status: 'ERROR', count: errorCount, bg: 'bg-rose-500', text: 'text-rose-700' },
  ];

  // 7-day trend calculations
  const trendPoints: TrendPoint[] = data?.jobs_last_7_days ?? [];
  const maxTrendTotal = Math.max(1, ...trendPoints.map((p) => p.total_jobs));
  const hasTrendActivity = trendPoints.some((point) => point.total_jobs > 0);

  // Submissions by course calculations
  const courses: CourseSubmission[] = data?.submissions_by_course ?? [];
  const maxCourseSubmissions = Math.max(1, ...courses.map((c) => c.submission_count));

  // Review requests breakdown
  const reviewRequestsByStatus = data?.review_requests_by_status ?? {};

  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#DDE2E8] pb-5">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Platform Analysis</h1>
          <p className="text-sm text-[#596579] mt-1">
            System performance metrics, background jobs, and operational statistics.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <nav aria-label="Admin shortcuts" className="hidden lg:flex items-center gap-2 text-xs font-semibold">
            <Link to="/admin/jobs" className="px-2.5 py-1.5 border border-[#DDE2E8] bg-white rounded-lg text-[#1F4B7A] hover:bg-slate-50">
              Monitoring
            </Link>
            <Link to="/admin/users" className="px-2.5 py-1.5 border border-[#DDE2E8] bg-white rounded-lg text-[#1F4B7A] hover:bg-slate-50">
              Users
            </Link>
            <Link to="/admin/audit" className="px-2.5 py-1.5 border border-[#DDE2E8] bg-white rounded-lg text-[#1F4B7A] hover:bg-slate-50">
              Audit
            </Link>
          </nav>
          <button
            type="button"
            disabled={dashboardQuery.isFetching}
            onClick={() => void dashboardQuery.refetch()}
            className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#DDE2E8] bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 rounded-lg transition-colors disabled:opacity-50 shrink-0"
            title="Refresh dashboard metrics"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${dashboardQuery.isFetching ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {dashboardQuery.error && (
        <div role="alert" className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-sm flex items-center justify-between">
          <span>Failed to load operations metrics: {getErrorMessage(dashboardQuery.error)}</span>
          <button
            type="button"
            onClick={() => void dashboardQuery.refetch()}
            className="inline-flex items-center gap-1 font-semibold text-[#1F4B7A] hover:underline"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      )}

      {/* KPI Cards Grid */}
      <section aria-label="Key Performance Indicators" className="grid grid-cols-2 lg:grid-cols-6 gap-3 sm:gap-4">
        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Users</span>
            <Users className="w-4 h-4 text-[#1F4B7A]" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : (data?.total_users ?? 0)}
            </p>
            <Link to="/admin/users" className="text-[11px] font-semibold text-[#1F4B7A] hover:underline mt-1 inline-flex items-center gap-0.5">
              <span>Manage users</span>
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>

        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Queued</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : queuedCount}
            </p>
            <span className="text-[11px] text-[#8893A5]">Awaiting worker</span>
          </div>
        </div>

        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Running</span>
            <Activity className="w-4 h-4 text-sky-500" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : runningCount}
            </p>
            <span className="text-[11px] text-[#8893A5]">Active processing</span>
          </div>
        </div>

        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Errors</span>
            <AlertTriangle className="w-4 h-4 text-rose-500" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : errorCount}
            </p>
            <Link to="/admin/jobs" className="text-[11px] font-semibold text-rose-600 hover:underline mt-1 inline-flex items-center gap-0.5">
              <span>View failures</span>
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>

        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Appeals</span>
            <MessageSquare className="w-4 h-4 text-[#1F4B7A]" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : (data?.open_review_requests ?? 0)}
            </p>
            <Link to="/admin/appeals" className="text-[11px] font-semibold text-[#1F4B7A] hover:underline mt-1 inline-flex items-center gap-0.5">
              <span>Open appeals</span>
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
        </div>

        <div className="p-4 bg-white border border-[#DDE2E8] rounded-xl flex flex-col justify-between">
          <div className="flex items-center justify-between text-[#8893A5] mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Avg Active Age</span>
            <Clock className="w-4 h-4 text-slate-500" />
          </div>
          <div>
            <p className="text-2xl font-bold text-slate-900">
              {dashboardQuery.isLoading ? '—' : formatDuration(data?.average_active_job_age_seconds ?? 0)}
            </p>
            <span className="text-[11px] text-[#8893A5]">Active runtime</span>
          </div>
        </div>
      </section>

      {/* Loading Skeleton */}
      {dashboardQuery.isLoading && (
        <div className="bg-white border border-[#DDE2E8] rounded-xl p-12 text-center text-slate-400 flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
          <span className="text-sm">Loading platform analytics...</span>
        </div>
      )}

      {data && (
        <>
          {/* Visualizations Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 1. Job Status Distribution */}
            <section
              aria-labelledby="job-status-distribution-title"
              className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <BarChart2 className="w-4 h-4 text-[#1F4B7A]" />
                    <h2 id="job-status-distribution-title" className="text-base font-bold text-slate-900">
                      Job Status Distribution
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowStatusTable(!showStatusTable)}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-[#1F4B7A] hover:underline"
                    aria-expanded={showStatusTable}
                  >
                    <Table className="w-3.5 h-3.5" />
                    <span>{showStatusTable ? 'Hide Table' : 'Show Table'}</span>
                  </button>
                </div>
                <p className="text-xs text-[#596579] mt-1">
                  Lifetime breakdown of {totalJobs} total recorded analysis jobs.
                </p>

                {/* Visual Segmented Bar */}
                <div className="mt-4 space-y-2">
                  <div className="h-4 w-full bg-slate-100 rounded-full overflow-hidden flex" role="img" aria-label={`Job status distribution: ${statusItems.map(s => `${s.status}: ${s.count}`).join(', ')}`}>
                    {totalJobs === 0 ? (
                      <div className="w-full bg-slate-200" />
                    ) : (
                      statusItems.map((item) => {
                        const pct = (item.count / totalJobs) * 100;
                        if (pct <= 0) return null;
                        return (
                          <div
                            key={item.status}
                            style={{ width: `${pct}%` }}
                            className={`${item.bg} h-full transition-all`}
                            title={`${item.status}: ${item.count} (${pct.toFixed(1)}%)`}
                          />
                        );
                      })
                    )}
                  </div>

                  {/* Direct Status Legend with Numbers and Percentages */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 text-xs">
                    {statusItems.map((item) => {
                      const pct = totalJobs > 0 ? (item.count / totalJobs) * 100 : 0;
                      return (
                        <div key={item.status} className="p-2.5 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg">
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className={`w-2.5 h-2.5 rounded-full ${item.bg}`} />
                            <span className="font-semibold text-slate-700">{item.status}</span>
                          </div>
                          <p className="text-base font-bold text-slate-900">{item.count}</p>
                          <span className="text-[11px] text-[#8893A5]">{pct.toFixed(1)}%</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Accessible Semantic Data Table Alternative */}
              {showStatusTable && (
                <div className="mt-4 pt-3 border-t border-[#DDE2E8]">
                  <table className="w-full text-xs text-left">
                    <caption className="sr-only">Job Status Distribution Data Table</caption>
                    <thead className="bg-[#F5F7FA] text-[#596579] font-semibold">
                      <tr>
                        <th scope="col" className="p-2">Status</th>
                        <th scope="col" className="p-2 text-right">Job Count</th>
                        <th scope="col" className="p-2 text-right">Percentage</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {statusItems.map((item) => {
                        const pct = totalJobs > 0 ? (item.count / totalJobs) * 100 : 0;
                        return (
                          <tr key={item.status}>
                            <td className="p-2 font-medium text-slate-900">{item.status}</td>
                            <td className="p-2 text-right font-mono">{item.count}</td>
                            <td className="p-2 text-right font-mono">{pct.toFixed(1)}%</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* 2. 7-Day Job Activity & Error Trend */}
            <section
              aria-labelledby="job-trends-title"
              className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-[#1F4B7A]" />
                    <h2 id="job-trends-title" className="text-base font-bold text-slate-900">
                      7-Day Activity & Error Trend
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowTrendTable(!showTrendTable)}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-[#1F4B7A] hover:underline"
                    aria-expanded={showTrendTable}
                  >
                    <Table className="w-3.5 h-3.5" />
                    <span>{showTrendTable ? 'Hide Table' : 'Show Table'}</span>
                  </button>
                </div>
                <p className="text-xs text-[#596579] mt-1">
                  Daily processed analysis jobs and failure counts over the past 7 days.
                </p>

                {/* Native Accessible Visual Column Chart */}
                {!hasTrendActivity ? (
                  <div className="p-8 text-center text-slate-400 text-xs">
                    No trend history recorded in the last 7 days.
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    <div className="grid grid-cols-7 gap-2 items-end h-32 pt-4 px-1" role="img" aria-label="7-Day Job Trends Column Chart">
                      {trendPoints.map((point) => {
                        const totalHeightPct = (point.total_jobs / maxTrendTotal) * 100;
                        const errorHeightPct = point.total_jobs > 0 ? (point.error_jobs / point.total_jobs) * totalHeightPct : 0;
                        const dayLabel = point.day.slice(5); // MM-DD

                        return (
                          <div key={point.day} className="flex flex-col items-center h-full justify-end group">
                            <span className="text-[10px] font-bold text-slate-700 mb-1">
                              {point.total_jobs}
                            </span>
                            <div className="w-full max-w-[28px] bg-slate-100 rounded-t relative overflow-hidden flex flex-col justify-end" style={{ height: `${totalHeightPct}%` }}>
                              <div
                                className="w-full h-full bg-[#1F4B7A] rounded-t"
                                title={`Total: ${point.total_jobs}, Failed: ${point.error_jobs}, Avg: ${point.average_processing_seconds.toFixed(1)}s`}
                              />
                              {point.error_jobs > 0 && (
                                <div
                                  style={{ height: `${errorHeightPct}%` }}
                                  className="w-full bg-rose-500 absolute bottom-0 left-0"
                                  title={`Errors: ${point.error_jobs}`}
                                />
                              )}
                            </div>
                            <span className="text-[10px] text-[#8893A5] mt-1.5 truncate max-w-full font-mono">
                              {dayLabel}
                            </span>
                          </div>
                        );
                      })}
                    </div>

                    <div className="flex items-center justify-center gap-4 text-xs text-[#596579] pt-1">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-sm bg-[#1F4B7A]" />
                        <span>Total Jobs</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-sm bg-rose-500" />
                        <span>Failed Jobs</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Accessible Semantic Data Table Alternative */}
              {showTrendTable && trendPoints.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[#DDE2E8]">
                  <table className="w-full text-xs text-left">
                    <caption className="sr-only">7-Day Job Activity Data Table</caption>
                    <thead className="bg-[#F5F7FA] text-[#596579] font-semibold">
                      <tr>
                        <th scope="col" className="p-2">Date</th>
                        <th scope="col" className="p-2 text-right">Total</th>
                        <th scope="col" className="p-2 text-right">Errors</th>
                        <th scope="col" className="p-2 text-right">Avg Duration</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {trendPoints.map((p) => (
                        <tr key={p.day}>
                          <td className="p-2 font-mono text-slate-900">{p.day}</td>
                          <td className="p-2 text-right font-mono font-bold text-[#1F4B7A]">{p.total_jobs}</td>
                          <td className="p-2 text-right font-mono font-bold text-rose-600">{p.error_jobs}</td>
                          <td className="p-2 text-right font-mono text-[#596579]">{p.average_processing_seconds.toFixed(1)}s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          {/* Bottom Grid: Course Submissions & Review Requests */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Submissions by Course (2 cols) */}
            <section
              aria-labelledby="course-submissions-title"
              className="lg:col-span-2 bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <FolderOpen className="w-4 h-4 text-[#1F4B7A]" />
                  <h2 id="course-submissions-title" className="text-base font-bold text-slate-900">
                    Submissions by Course
                  </h2>
                </div>
                <Link to="/admin/courses" className="text-xs font-semibold text-[#1F4B7A] hover:underline">
                  View all courses
                </Link>
              </div>

              {courses.length === 0 ? (
                <div className="p-8 text-center text-slate-400 text-xs">
                  No courses with submissions recorded.
                </div>
              ) : (
                <div className="space-y-3">
                  {courses.map((course) => {
                    const widthPct = Math.max(4, (course.submission_count / maxCourseSubmissions) * 100);

                    return (
                      <div key={course.course_id} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <Link
                            to={`/admin/courses/${course.course_id}/submissions`}
                            className="font-semibold text-slate-900 hover:text-[#1F4B7A] hover:underline truncate max-w-[280px] sm:max-w-md"
                          >
                            {course.course_code} — {course.course_name}
                          </Link>
                          <span className="font-bold text-slate-900 font-mono shrink-0 ml-2">
                            {course.submission_count}
                          </span>
                        </div>
                        <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                          <div
                            style={{ width: `${widthPct}%` }}
                            className="h-full bg-[#1F4B7A] rounded-full"
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            {/* Review Requests Status (1 col) */}
            <section
              aria-labelledby="review-requests-status-title"
              className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileCheck className="w-4 h-4 text-[#1F4B7A]" />
                    <h2 id="review-requests-status-title" className="text-base font-bold text-slate-900">
                      Review Requests
                    </h2>
                  </div>
                  <Link to="/admin/appeals" className="text-xs font-semibold text-[#1F4B7A] hover:underline">
                    Appeals
                  </Link>
                </div>
                <p className="text-xs text-[#596579] mt-1">
                  Status breakdown of criterion review appeals.
                </p>

                <div className="mt-4 space-y-2.5">
                  {Object.entries(reviewRequestsByStatus).length === 0 ? (
                    <div className="p-6 text-center text-slate-400 text-xs">
                      No review requests recorded.
                    </div>
                  ) : (
                    Object.entries(reviewRequestsByStatus).map(([status, count]) => {
                      const isPending = status === 'PENDING' || status === 'SUBMITTED';
                      const isResolved = status === 'RESOLVED' || status === 'APPROVED';
                      const isRejected = status === 'REJECTED';

                      const badgeStyle = isPending
                        ? 'bg-amber-50 text-amber-800 border-amber-200'
                        : isResolved
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : isRejected
                        ? 'bg-rose-50 text-rose-800 border-rose-200'
                        : 'bg-slate-50 text-slate-800 border-slate-200';

                      return (
                        <div
                          key={status}
                          className="flex items-center justify-between p-3 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg text-xs"
                        >
                          <span className={`px-2 py-0.5 rounded font-semibold border ${badgeStyle}`}>
                            {status}
                          </span>
                          <span className="font-bold text-slate-900 text-sm font-mono">{count}</span>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="pt-3 border-t border-[#DDE2E8]">
                <Link
                  to="/admin/appeals"
                  className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 bg-[#1F4B7A] hover:bg-[#163657] text-white rounded-lg text-xs font-semibold transition-colors"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  <span>Inspect Review Appeals</span>
                </Link>
              </div>
            </section>
          </div>
        </>
      )}
    </div>
  );
};
