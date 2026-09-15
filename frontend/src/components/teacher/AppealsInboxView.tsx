import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  MessageSquare,
  CheckCircle2,
  XCircle,
  Clock,
  Send,
  X,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  Filter,
  User,
  FileText,
  AlertCircle,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type ReviewRequest = components['schemas']['ReviewRequestResponse'];
type ReviewRequestStatus = 'OPEN' | 'RESOLVED' | 'REJECTED';

function trapFocus(event: React.KeyboardEvent<HTMLDivElement>) {
  if (event.key !== 'Tab') return;
  const elements = Array.from(
    event.currentTarget.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ),
  );
  if (elements.length === 0) return;
  const first = elements[0];
  const last = elements[elements.length - 1];
  const wrap = event.shiftKey
    ? document.activeElement === first || document.activeElement === event.currentTarget
    : document.activeElement === last;
  if (!wrap) return;
  event.preventDefault();
  (event.shiftKey ? last : first)?.focus();
}

interface RequestDetailModalProps {
  requestId: string;
  onClose: () => void;
  onResponded: () => void;
}

const RequestDetailModal: React.FC<RequestDetailModalProps> = ({
  requestId,
  onClose,
  onResponded,
}) => {
  const [resolutionStatus, setResolutionStatus] = useState<'RESOLVED' | 'REJECTED'>('RESOLVED');
  const [responseText, setResponseText] = useState('');
  const [submitError, setSubmitError] = useState<string>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const queryClient = useQueryClient();
  const modalRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

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

  useEffect(() => {
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modalRef.current?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      restoreFocusRef.current?.focus();
    };
  }, [onClose]);

  const request = requestQuery.data;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!request || !responseText.trim()) return;

    setIsSubmitting(true);
    setSubmitError(undefined);

    try {
      await apiData(
        api.PATCH('/api/v1/review-requests/{review_request_id}', {
          params: { path: { review_request_id: request.id } },
          body: {
            status: resolutionStatus,
            response: responseText.trim(),
          },
        }),
      );
      await queryClient.invalidateQueries({ queryKey: ['review-requests'] });
      await queryClient.invalidateQueries({ queryKey: ['review-request', requestId] });
      await queryClient.invalidateQueries({ queryKey: ['notifications'] });
      onResponded();
      onClose();
    } catch (err) {
      setSubmitError(getErrorMessage(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="appeal-dialog-title"
        tabIndex={-1}
        onKeyDown={trapFocus}
        className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-xl p-6 space-y-5 text-xs outline-hidden animate-in fade-in zoom-in-95 duration-150"
      >
        {/* Modal Header */}
        <div className="border-b border-slate-100 pb-3.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-[#EAF1F8] text-[#1F4B7A]">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div>
              <h2 id="appeal-dialog-title" className="font-bold text-sm text-slate-900">
                Criterion Review Request
              </h2>
              <p className="text-[11px] text-slate-500 font-mono">ID: {requestId}</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        {requestQuery.isLoading ? (
          <div className="py-12 text-center text-slate-400 flex flex-col items-center gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
            <p className="text-sm">Loading review request details...</p>
          </div>
        ) : requestQuery.isError || !request ? (
          <div className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 space-y-2">
            <div className="flex items-center gap-2 font-semibold">
              <AlertCircle className="w-4 h-4 text-rose-600" />
              <span>Could not load review request</span>
            </div>
            <p className="text-xs">{getErrorMessage(requestQuery.error)}</p>
            <p className="text-[11px] text-rose-600">
              The request may not exist or may belong to a course you do not instruct.
            </p>
            <div className="pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 bg-rose-800 text-white rounded-lg text-xs font-semibold"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Metadata Info Grid */}
            <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 space-y-2.5">
              <div className="grid grid-cols-2 gap-2 text-slate-600 text-[11px]">
                <div>
                  <span className="text-slate-400 block font-medium">Student ID</span>
                  <span className="font-mono text-slate-800 break-all">{request.student_id}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-medium">Status</span>
                  {request.status === 'OPEN' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                      <Clock className="w-3 h-3" /> OPEN
                    </span>
                  ) : request.status === 'RESOLVED' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <CheckCircle2 className="w-3 h-3" /> RESOLVED
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                      <XCircle className="w-3 h-3" /> REJECTED
                    </span>
                  )}
                </div>
                <div>
                  <span className="text-slate-400 block font-medium">Submission ID</span>
                  <span className="font-mono text-slate-800 break-all">{request.submission_id}</span>
                </div>
                <div>
                  <span className="text-slate-400 block font-medium">Submitted at</span>
                  <span className="text-slate-800">{new Date(request.created_at).toLocaleString()}</span>
                </div>
              </div>

              {request.criterion_id && (
                <div className="pt-1 border-t border-slate-200/60">
                  <span className="text-slate-400 text-[10px] block font-semibold uppercase tracking-wider">
                    Target Criterion
                  </span>
                  <span className="font-mono text-slate-800 text-[11px] break-all">
                    {request.criterion_id}
                  </span>
                </div>
              )}

              {request.finding_id && (
                <div className="pt-1 border-t border-slate-200/60">
                  <span className="text-slate-400 text-[10px] block font-semibold uppercase tracking-wider">
                    Target Finding
                  </span>
                  <span className="font-mono text-slate-800 text-[11px] break-all">
                    {request.finding_id}
                  </span>
                </div>
              )}

              <div className="pt-1 border-t border-slate-200/60">
                <span className="text-slate-400 text-[10px] block font-semibold uppercase tracking-wider">
                  Student Appeal Reason
                </span>
                <p className="text-slate-800 text-xs leading-relaxed mt-0.5 whitespace-pre-wrap">
                  {request.reason}
                </p>
              </div>
            </div>

            {/* If request is OPEN: Show response form */}
            {request.status === 'OPEN' ? (
              <form onSubmit={handleSubmit} className="space-y-4">
                {submitError && (
                  <div
                    role="alert"
                    className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-xs"
                  >
                    {submitError}
                  </div>
                )}

                <div>
                  <label id="decision-label" className="block text-slate-700 font-semibold mb-1.5">
                    Resolution Decision
                  </label>
                  <div className="grid grid-cols-2 gap-2.5" role="group" aria-labelledby="decision-label">
                    <button
                      type="button"
                      aria-pressed={resolutionStatus === 'RESOLVED'}
                      onClick={() => setResolutionStatus('RESOLVED')}
                      className={`py-2.5 px-3 rounded-xl font-semibold border text-center transition-all flex items-center justify-center gap-2 ${
                        resolutionStatus === 'RESOLVED'
                          ? 'bg-emerald-50 text-emerald-800 border-emerald-300 ring-2 ring-emerald-500/20'
                          : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span>Accept / Resolve</span>
                    </button>
                    <button
                      type="button"
                      aria-pressed={resolutionStatus === 'REJECTED'}
                      onClick={() => setResolutionStatus('REJECTED')}
                      className={`py-2.5 px-3 rounded-xl font-semibold border text-center transition-all flex items-center justify-center gap-2 ${
                        resolutionStatus === 'REJECTED'
                          ? 'bg-rose-50 text-rose-800 border-rose-300 ring-2 ring-rose-500/20'
                          : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <XCircle className="w-4 h-4 text-rose-600" />
                      <span>Reject / Keep score</span>
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="response-textarea" className="block text-slate-700 font-semibold mb-1">
                    Instructor Explanation & Feedback <span className="text-rose-500">*</span>
                  </label>
                  <textarea
                    id="response-textarea"
                    required
                    rows={4}
                    maxLength={4000}
                    value={responseText}
                    onChange={(e) => setResponseText(e.target.value)}
                    placeholder="Provide reasoning and guidance for the student..."
                    className="w-full px-3.5 py-2.5 border border-slate-300 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A] leading-relaxed text-xs"
                  />
                  <span className="text-[10px] text-slate-400 block text-right mt-0.5">
                    {responseText.length} / 4000
                  </span>
                </div>

                <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2.5">
                  <button
                    type="button"
                    onClick={onClose}
                    className="px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-medium hover:bg-slate-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting || !responseText.trim()}
                    className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 disabled:opacity-40 transition-colors"
                  >
                    {isSubmitting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Submitting...</span>
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4" />
                        <span>Submit Response</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              /* If request is already RESOLVED or REJECTED: Show response read-only */
              <div className="space-y-3 pt-2">
                <div
                  className={`p-3.5 rounded-xl border space-y-1.5 ${
                    request.status === 'RESOLVED'
                      ? 'bg-emerald-50/50 border-emerald-200 text-emerald-900'
                      : 'bg-rose-50/50 border-rose-200 text-rose-900'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-xs uppercase tracking-wider">
                      Instructor Decision: {request.status}
                    </span>
                    {request.responded_at && (
                      <span className="text-[10px] opacity-75">
                        {new Date(request.responded_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                  {request.responded_by_user_id && (
                    <p className="text-[11px] font-mono opacity-80">
                      Responded by: {request.responded_by_user_id}
                    </p>
                  )}
                  <div className="mt-2 pt-2 border-t border-current/10">
                    <span className="font-semibold block text-[11px] mb-0.5">Response:</span>
                    <p className="text-xs leading-relaxed whitespace-pre-wrap">{request.response}</p>
                  </div>
                </div>

                <div className="pt-3 border-t border-slate-100 flex justify-end">
                  <button
                    type="button"
                    onClick={onClose}
                    className="px-4 py-2 rounded-xl bg-slate-900 text-white font-semibold hover:bg-slate-800 transition-colors"
                  >
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export const AppealsInboxView: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const courseIdParam = searchParams.get('courseId') || '';
  const statusParam = searchParams.get('status') || '';
  const pageParam = parseInt(searchParams.get('page') || '1', 10);
  const page = isNaN(pageParam) || pageParam < 1 ? 1 : pageParam;
  const requestIdParam = searchParams.get('requestId') || '';

  const [feedbackBanner, setFeedbackBanner] = useState<string>();

  // 1. Fetch instructor courses
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });

  const courses = coursesQuery.data ?? [];

  // Default course selection if not present
  useEffect(() => {
    if (courses.length > 0 && !courseIdParam) {
      const next = new URLSearchParams(searchParams);
      next.set('courseId', courses[0].id);
      setSearchParams(next, { replace: true });
    }
  }, [courses, courseIdParam, searchParams, setSearchParams]);

  const selectedCourseId = courseIdParam || (courses[0]?.id ?? '');

  // 2. Fetch review requests for course
  const validStatus: ReviewRequestStatus | undefined =
    statusParam === 'OPEN' || statusParam === 'RESOLVED' || statusParam === 'REJECTED'
      ? (statusParam as ReviewRequestStatus)
      : undefined;

  const appealsQuery = useQuery({
    queryKey: ['review-requests', selectedCourseId, validStatus, page],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/courses/{course_id}/review-requests', {
          params: {
            path: { course_id: selectedCourseId },
            query: {
              ...(validStatus ? { status: validStatus } : {}),
              page,
              page_size: 20,
            },
          },
        }),
      ),
    enabled: Boolean(selectedCourseId),
  });

  const handleCourseSelect = (newCourseId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('courseId', newCourseId);
    next.set('page', '1');
    setSearchParams(next);
  };

  const handleStatusFilter = (newStatus: string) => {
    const next = new URLSearchParams(searchParams);
    if (newStatus && newStatus !== 'ALL') {
      next.set('status', newStatus);
    } else {
      next.delete('status');
    }
    next.set('page', '1');
    setSearchParams(next);
  };

  const handlePageChange = (newPage: number) => {
    const next = new URLSearchParams(searchParams);
    next.set('page', String(newPage));
    setSearchParams(next);
  };

  const handleOpenModal = (reqId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('requestId', reqId);
    setSearchParams(next);
  };

  const handleCloseModal = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('requestId');
    setSearchParams(next);
  };

  const totalItems = appealsQuery.data?.total ?? 0;
  const pageSize = appealsQuery.data?.page_size ?? 20;
  const totalPages = Math.ceil(totalItems / pageSize) || 1;
  const requests = appealsQuery.data?.items ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2.5">
          <MessageSquare className="w-5 h-5 text-[#1F4B7A]" />
          <span>Criterion Review Requests</span>
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Review student appeals on criteria scores, inspect submitted reasons, and resolve or reject requests.
        </p>
      </div>

      {feedbackBanner && (
        <div
          role="status"
          className="p-3 rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-800 text-xs flex items-center justify-between"
        >
          <span>{feedbackBanner}</span>
          <button
            type="button"
            onClick={() => setFeedbackBanner(undefined)}
            className="text-emerald-600 hover:text-emerald-800 font-bold"
          >
            ✕
          </button>
        </div>
      )}

      {/* Course Selector & Filters */}
      <div className="bg-white p-4 rounded-xl border border-[#DDE2E8] shadow-2xs flex flex-wrap items-center justify-between gap-4">
        {/* Course Select */}
        <div className="flex items-center gap-3 min-w-[280px]">
          <label htmlFor="course-select" className="text-xs font-semibold text-slate-700 whitespace-nowrap">
            Course:
          </label>
          {coursesQuery.isLoading ? (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Loading courses...</span>
            </div>
          ) : courses.length === 0 ? (
            <span className="text-xs text-amber-700 font-medium">No courses available</span>
          ) : (
            <select
              id="course-select"
              value={selectedCourseId}
              onChange={(e) => handleCourseSelect(e.target.value)}
              className="w-full text-xs font-medium bg-slate-50 border border-slate-300 rounded-lg px-3 py-2 text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A]"
            >
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.code} - {course.name} ({course.term})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Status Filter Tabs */}
        <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs">
          <button
            type="button"
            onClick={() => handleStatusFilter('ALL')}
            className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
              !statusParam || statusParam === 'ALL'
                ? 'bg-white text-slate-900 shadow-2xs font-semibold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            All
          </button>
          <button
            type="button"
            onClick={() => handleStatusFilter('OPEN')}
            className={`px-3 py-1.5 rounded-md font-medium transition-colors flex items-center gap-1 ${
              statusParam === 'OPEN'
                ? 'bg-white text-amber-800 shadow-2xs font-semibold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <Clock className="w-3 h-3 text-amber-600" />
            <span>Open</span>
          </button>
          <button
            type="button"
            onClick={() => handleStatusFilter('RESOLVED')}
            className={`px-3 py-1.5 rounded-md font-medium transition-colors flex items-center gap-1 ${
              statusParam === 'RESOLVED'
                ? 'bg-white text-emerald-800 shadow-2xs font-semibold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            <span>Resolved</span>
          </button>
          <button
            type="button"
            onClick={() => handleStatusFilter('REJECTED')}
            className={`px-3 py-1.5 rounded-md font-medium transition-colors flex items-center gap-1 ${
              statusParam === 'REJECTED'
                ? 'bg-white text-rose-800 shadow-2xs font-semibold'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            <XCircle className="w-3 h-3 text-rose-600" />
            <span>Rejected</span>
          </button>
        </div>
      </div>

      {/* Review Requests List Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        {coursesQuery.isError ? (
          <div role="alert" className="p-8 text-center text-rose-700">
            <p className="font-semibold">Failed to load courses</p>
            <p className="text-xs mt-1">{getErrorMessage(coursesQuery.error)}</p>
          </div>
        ) : courses.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <p className="font-semibold text-slate-700">No courses assigned</p>
            <p className="text-xs mt-1">You must be an instructor of a course to review appeals.</p>
          </div>
        ) : appealsQuery.isLoading ? (
          <div className="p-12 text-center text-slate-400 flex flex-col items-center gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
            <p className="text-xs">Loading review requests...</p>
          </div>
        ) : appealsQuery.isError ? (
          <div role="alert" className="p-8 text-center text-rose-700 space-y-2">
            <p className="font-semibold">Failed to load review requests</p>
            <p className="text-xs">{getErrorMessage(appealsQuery.error)}</p>
            <button
              type="button"
              onClick={() => void appealsQuery.refetch()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-semibold mt-2"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry</span>
            </button>
          </div>
        ) : requests.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 text-slate-300 stroke-1" />
            <p className="font-semibold text-slate-700">No review requests found</p>
            <p className="text-xs mt-0.5">
              {validStatus
                ? `No ${validStatus.toLowerCase()} review requests for this course.`
                : 'No review requests have been submitted for this course.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
                <tr>
                  <th scope="col" className="px-4 py-3">Student / Request ID</th>
                  <th scope="col" className="px-4 py-3">Target</th>
                  <th scope="col" className="px-4 py-3">Appeal Reason</th>
                  <th scope="col" className="px-4 py-3">Submitted</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {requests.map((request) => (
                  <tr key={request.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-4 py-3.5">
                      <div className="font-mono text-xs font-semibold text-slate-900 truncate max-w-[140px]" title={request.student_id}>
                        {request.student_id}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono truncate max-w-[140px]" title={request.id}>
                        req: {request.id}
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      {request.criterion_id ? (
                        <div>
                          <span className="text-[10px] font-bold text-slate-400 block uppercase">Criterion</span>
                          <span className="font-mono text-[11px] text-slate-800 break-all max-w-[160px] block" title={request.criterion_id}>
                            {request.criterion_id}
                          </span>
                        </div>
                      ) : request.finding_id ? (
                        <div>
                          <span className="text-[10px] font-bold text-slate-400 block uppercase">Finding</span>
                          <span className="font-mono text-[11px] text-slate-800 break-all max-w-[160px] block" title={request.finding_id}>
                            {request.finding_id}
                          </span>
                        </div>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 max-w-xs">
                      <p className="text-slate-700 line-clamp-2 leading-relaxed">{request.reason}</p>
                      {request.response && (
                        <p className="text-[11px] text-slate-600 mt-1 bg-slate-100/70 p-1.5 rounded-md line-clamp-1">
                          <span className="font-semibold">Response:</span> {request.response}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-slate-500 whitespace-nowrap text-[11px]">
                      {new Date(request.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3.5 whitespace-nowrap">
                      {request.status === 'OPEN' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                          <Clock className="w-3 h-3" />
                          <span>Open</span>
                        </span>
                      ) : request.status === 'RESOLVED' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Resolved</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                          <XCircle className="w-3 h-3" />
                          <span>Rejected</span>
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => handleOpenModal(request.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                          request.status === 'OPEN'
                            ? 'bg-slate-900 text-white hover:bg-slate-800'
                            : 'bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200'
                        }`}
                      >
                        {request.status === 'OPEN' ? 'Respond' : 'View Detail'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        {requests.length > 0 && (
          <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs">
            <span className="text-slate-500">
              Showing page <span className="font-semibold text-slate-800">{page}</span> of{' '}
              <span className="font-semibold text-slate-800">{totalPages}</span> ({totalItems} total)
            </span>
            <div className="flex items-center gap-1.5" aria-label="Pagination">
              <button
                type="button"
                disabled={page <= 1}
                aria-label="Previous page"
                onClick={() => handlePageChange(page - 1)}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                type="button"
                disabled={page >= totalPages}
                aria-label="Next page"
                onClick={() => handlePageChange(page + 1)}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-40 disabled:hover:bg-transparent"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Modal Dialog for Deep-link or Item Selection */}
      {requestIdParam && (
        <RequestDetailModal
          requestId={requestIdParam}
          onClose={handleCloseModal}
          onResponded={() => {
            setFeedbackBanner(`Review request ${requestIdParam} successfully updated.`);
            void queryClient.invalidateQueries({ queryKey: ['review-requests'] });
          }}
        />
      )}
    </div>
  );
};
