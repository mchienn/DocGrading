import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  Bell,
  CalendarClock,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Download,
  ChevronUp,
  FileText,
  Pencil,
  Plus,
  Send,
  Square,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import type { components } from '../../api/schema';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { ApiAssignment, ApiCourse, ApiRubric } from '../../types/api';
import { AssignmentWizardModal } from './AssignmentWizardModal';

type AssignmentInput = components['schemas']['AssignmentCreate'];
type AnnouncementInput = components['schemas']['AnnouncementCreate'];
type Announcement = components['schemas']['AnnouncementResponse'];
type SubmissionVersion = components['schemas']['SubmissionVersionResponse'];

interface CourseWorkspaceViewProps {
  course: ApiCourse;
  assignments: ApiAssignment[];
  rubrics: ApiRubric[];
  announcements: Announcement[];
  loading: boolean;
  error?: string;
  onBack: () => void;
  onOpenSubmissionQueue: () => void;
  onOpenRoster: () => void;
  onOpenSubmission: (submissionId: string, documentStatus?: string | null) => void;
  onOpenVersionResult: (documentVersionId: string) => void;
  onSaveAssignment: (input: AssignmentInput, assignmentId?: string) => Promise<void>;
  onDeleteAssignment: (assignmentId: string) => Promise<void>;
  onPublishAssignment: (assignmentId: string) => Promise<void>;
  onCloseAssignment: (assignmentId: string) => Promise<void>;
  onSaveAnnouncement: (input: AnnouncementInput, announcementId?: string) => Promise<void>;
  onDeleteAnnouncement: (announcementId: string) => Promise<void>;
}

const reviewableStatuses = ['AWAITING_REVIEW', 'APPROVED', 'PUBLISHED'];

interface SubmissionAttemptHistoryProps {
  submissionId: string;
  openingDocumentId?: string;
  onOpenPdf: (documentVersionId: string) => Promise<void>;
  onOpenResult: (documentVersionId: string) => void;
}

const SubmissionAttemptHistory: React.FC<SubmissionAttemptHistoryProps> = ({
  submissionId,
  openingDocumentId,
  onOpenPdf,
  onOpenResult,
}) => {
  const versionsQuery = useQuery({
    queryKey: ['submission-versions', submissionId],
    queryFn: () => apiData(api.GET('/api/v1/submissions/{submission_id}/versions', {
      params: {
        path: { submission_id: submissionId },
        query: { page: 1, page_size: 100 },
      },
    })),
  });
  const versions = [...(versionsQuery.data?.items ?? [])].reverse();

  return (
    <tr className="bg-sky-50/40">
      <td id={`submission-attempts-${submissionId}`} colSpan={6} className="px-4 py-4">
        <div className="rounded-lg border border-sky-200 bg-white overflow-hidden">
          <div className="px-3 py-2 border-b border-sky-100">
            <h4 className="text-xs font-bold text-slate-800">Submission attempts</h4>
          </div>
          {versionsQuery.isLoading ? (
            <p className="px-3 py-5 text-xs text-slate-500">Loading attempts...</p>
          ) : versionsQuery.error ? (
            <p role="alert" className="px-3 py-5 text-xs text-rose-700">
              {getErrorMessage(versionsQuery.error)}
            </p>
          ) : versions.length === 0 ? (
            <p className="px-3 py-5 text-xs text-slate-500">No attempts.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Attempt</th>
                    <th className="px-3 py-2">File</th>
                    <th className="px-3 py-2">Submitted</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {versions.map((version: SubmissionVersion) => (
                    <tr key={version.document_version_id}>
                      <td className="px-3 py-2 font-semibold">#{version.version_number}</td>
                      <td className="px-3 py-2">
                        <p className="max-w-64 truncate font-medium text-slate-700" title={version.filename}>
                          {version.filename}
                        </p>
                        <p className="text-[11px] text-slate-500">{version.file_size_bytes.toLocaleString()} bytes</p>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                        {new Date(version.created_at).toLocaleString()}
                      </td>
                      <td className="px-3 py-2">
                        <span className="font-mono">
                          {version.processing_status}
                          {version.publication_status ? ` · ${version.publication_status}` : ''}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => onOpenResult(version.document_version_id)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 px-2.5 py-1.5 font-semibold text-sky-800 hover:bg-sky-50"
                        >
                          <ClipboardCheck className="w-3.5 h-3.5" /> Result
                        </button>
                        <button
                          type="button"
                          disabled={openingDocumentId === version.document_version_id}
                          onClick={() => void onOpenPdf(version.document_version_id)}
                          className="ml-1 p-2 text-sky-700 hover:bg-sky-50 rounded-lg disabled:opacity-40"
                          aria-label={`Open attempt ${version.version_number}: ${version.filename}`}
                        >
                          <Download className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </td>
    </tr>
  );
};

export const CourseWorkspaceView: React.FC<CourseWorkspaceViewProps> = ({
  course,
  assignments,
  rubrics,
  announcements,
  loading,
  error,
  onBack,
  onOpenSubmissionQueue,
  onOpenRoster,
  onOpenSubmission,
  onOpenVersionResult,
  onSaveAssignment,
  onDeleteAssignment,
  onPublishAssignment,
  onCloseAssignment,
  onSaveAnnouncement,
  onDeleteAnnouncement,
}) => {
  const [activeTab, setActiveTab] = useState<'assignments' | 'announcements'>('assignments');
  const [showAssignmentForm, setShowAssignmentForm] = useState(false);
  const [editingAssignment, setEditingAssignment] = useState<ApiAssignment>();
  const [expandedAssignmentId, setExpandedAssignmentId] = useState<string>();
  const [submissionPage, setSubmissionPage] = useState(1);
  const [showAnnouncementForm, setShowAnnouncementForm] = useState(false);
  const [expandedSubmissionId, setExpandedSubmissionId] = useState<string>();
  const [editingAnnouncement, setEditingAnnouncement] = useState<Announcement>();
  const [announcementTitle, setAnnouncementTitle] = useState('');
  const [announcementBody, setAnnouncementBody] = useState('');
  const [announcementSaving, setAnnouncementSaving] = useState(false);
  const [openingDocumentId, setOpeningDocumentId] = useState<string>();
  const [actionError, setActionError] = useState<string>();

  const submissionsQuery = useQuery({
    queryKey: ['assignment-submissions', expandedAssignmentId, submissionPage],
    queryFn: () => apiData(api.GET('/api/v1/assignments/{assignment_id}/submissions', {
      params: {
        path: { assignment_id: expandedAssignmentId ?? '' },
        query: { page: submissionPage, page_size: 25 },
      },
    })),
    enabled: Boolean(expandedAssignmentId),
  });
  const submissions = submissionsQuery.data;
  const submissionPages = Math.max(1, Math.ceil((submissions?.total ?? 0) / 25));

  const runAction = async (action: () => Promise<void>) => {
    setActionError(undefined);
    try {
      await action();
    } catch (requestError) {
      setActionError(getErrorMessage(requestError));
    }
  };

  const startAnnouncement = (announcement?: Announcement) => {
    setEditingAnnouncement(announcement);
    setAnnouncementTitle(announcement?.title ?? '');
    setAnnouncementBody(announcement?.body ?? '');
    setShowAnnouncementForm(true);
  };

  const saveAnnouncement = async (event: React.FormEvent) => {
    event.preventDefault();
    const title = announcementTitle.trim();
    const body = announcementBody.trim();
    if (!title || !body) {
      setActionError('Announcement title and body cannot be blank.');
      return;
    }
    setAnnouncementSaving(true);
    setActionError(undefined);
    try {
      await onSaveAnnouncement({ title, body }, editingAnnouncement?.id);
      setEditingAnnouncement(undefined);
      setAnnouncementTitle('');
      setAnnouncementBody('');
      setShowAnnouncementForm(false);
    } catch (requestError) {
      setActionError(getErrorMessage(requestError));
    } finally {
      setAnnouncementSaving(false);
    }
  };

  const openPdf = async (documentVersionId: string) => {
    setOpeningDocumentId(documentVersionId);
    setActionError(undefined);
    try {
      const download = await apiData(api.GET('/api/v1/document-versions/{version_id}/download', {
        params: { path: { version_id: documentVersionId } },
      }));
      const link = document.createElement('a');
      link.href = download.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.click();
    } catch (requestError) {
      setActionError(getErrorMessage(requestError));
    } finally {
      setOpeningDocumentId(undefined);
    }
  };

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    let nextTab: 'assignments' | 'announcements' | undefined;
    if (event.key === 'Home') nextTab = 'assignments';
    if (event.key === 'End') nextTab = 'announcements';
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      nextTab = activeTab === 'assignments' ? 'announcements' : 'assignments';
    }
    if (!nextTab) return;
    event.preventDefault();
    setActiveTab(nextTab);
    document.getElementById(`course-tab-${nextTab}`)?.focus();
  };

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900">
        <ArrowLeft className="w-4 h-4" /> Back to courses
      </button>

      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>
          <h1 className="text-2xl font-bold text-slate-900 mt-1">{course.name}</h1>
          <p className="text-sm text-slate-500 mt-1">{course.term} · {course.status}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onOpenRoster} className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-sm font-semibold hover:bg-slate-50">
            <Users className="w-4 h-4" /> Roster
          </button>
          <button type="button" onClick={onOpenSubmissionQueue} className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-sm font-semibold hover:bg-slate-50">
            <ClipboardCheck className="w-4 h-4" /> All submissions
          </button>
        </div>
      </div>

      <details className="bg-white border border-slate-200 rounded-xl">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">
          Course details
        </summary>
        <dl className="grid gap-4 border-t border-slate-200 px-4 py-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Course owner</dt>
            <dd className="mt-1 font-semibold text-slate-900">{course.owner.display_name}</dd>
            <dd className="text-xs text-slate-500">
              <a className="hover:underline" href={`mailto:${course.owner.email}`}>{course.owner.email}</a>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Created</dt>
            <dd className="mt-1 text-slate-700">{new Date(course.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Last updated</dt>
            <dd className="mt-1 text-slate-700">{new Date(course.updated_at).toLocaleString()}</dd>
          </div>
        </dl>
      </details>

      {(error || actionError) && (
        <div role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {actionError ?? error}
        </div>
      )}

      <div role="tablist" aria-label="Course content" className="inline-flex p-1 bg-slate-100 border border-slate-200 rounded-xl">
        <button id="course-tab-assignments" type="button" role="tab" aria-selected={activeTab === 'assignments'} aria-controls="course-panel-assignments" tabIndex={activeTab === 'assignments' ? 0 : -1} onClick={() => setActiveTab('assignments')} onKeyDown={handleTabKeyDown} className={`px-4 py-2 rounded-lg text-sm font-semibold ${activeTab === 'assignments' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'}`}>
          Assignments ({assignments.length})
        </button>
        <button id="course-tab-announcements" type="button" role="tab" aria-selected={activeTab === 'announcements'} aria-controls="course-panel-announcements" tabIndex={activeTab === 'announcements' ? 0 : -1} onClick={() => setActiveTab('announcements')} onKeyDown={handleTabKeyDown} className={`px-4 py-2 rounded-lg text-sm font-semibold ${activeTab === 'announcements' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600'}`}>
          Announcements ({announcements.length})
        </button>
      </div>

      {activeTab === 'assignments' ? (
        <section id="course-panel-assignments" role="tabpanel" aria-labelledby="course-tab-assignments" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Assignments</h2>
              <p className="text-xs text-slate-500 mt-0.5">Create, publish, close, and inspect each assignment's submissions.</p>
            </div>
            {course.status === 'ACTIVE' && (
              <button type="button" onClick={() => { setEditingAssignment(undefined); setShowAssignmentForm(true); }} className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold">
                <Plus className="w-4 h-4" /> Create assignment
              </button>
            )}
          </div>

          {loading ? (
            <p className="text-sm text-slate-500">Loading assignments...</p>
          ) : assignments.length === 0 ? (
            <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No assignments in this course.</p>
          ) : (
            <div className="space-y-3">
              {assignments.map((assignment) => {
                const expanded = expandedAssignmentId === assignment.id;
                return (
                  <article key={assignment.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                    <div className="p-5 flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-bold text-slate-900">{assignment.title}</h3>
                          <span className="text-[11px] font-semibold px-2 py-0.5 rounded border bg-slate-50 text-slate-600 border-slate-200">{assignment.status}</span>
                        </div>
                        {assignment.description && <p className="text-sm text-slate-600 mt-2">{assignment.description}</p>}
                        <p className="text-xs text-slate-500 mt-3 flex items-center gap-1.5">
                          <CalendarClock className="w-3.5 h-3.5" /> Due {new Date(assignment.due_at).toLocaleString()} · max {assignment.max_submissions} attempts
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 shrink-0">
                        <button
                          type="button"
                          onClick={() => {
                            setSubmissionPage(1);
                            setExpandedAssignmentId(expanded ? undefined : assignment.id);
                          }}
                          className="inline-flex items-center gap-1.5 px-3 py-2 border border-slate-300 bg-white text-slate-700 rounded-lg text-xs font-semibold"
                        >
                          <FileText className="w-3.5 h-3.5" /> {expanded ? 'Hide submissions' : 'Submissions'}
                        </button>
                        {course.status === 'ACTIVE' && assignment.status === 'DRAFT' && (
                          <>
                            <button type="button" onClick={() => { setEditingAssignment(assignment); setShowAssignmentForm(true); }} className="p-2 border border-slate-200 rounded-lg text-slate-600" aria-label={`Edit ${assignment.title}`}>
                              <Pencil className="w-4 h-4" />
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (window.confirm(`Delete draft “${assignment.title}”?`)) void runAction(() => onDeleteAssignment(assignment.id));
                              }}
                              className="p-2 border border-rose-200 rounded-lg text-rose-700"
                              aria-label={`Delete ${assignment.title}`}
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                            <button type="button" onClick={() => void runAction(() => onPublishAssignment(assignment.id))} className="inline-flex items-center gap-1.5 px-3 py-2 bg-emerald-700 text-white rounded-lg text-xs font-semibold">
                              <Send className="w-3.5 h-3.5" /> Publish
                            </button>
                          </>
                        )}
                        {course.status === 'ACTIVE' && assignment.status === 'OPEN' && (
                          <button type="button" onClick={() => void runAction(() => onCloseAssignment(assignment.id))} className="inline-flex items-center gap-1.5 px-3 py-2 bg-slate-800 text-white rounded-lg text-xs font-semibold">
                            <Square className="w-3.5 h-3.5" /> Close
                          </button>
                        )}
                      </div>
                    </div>

                    {expanded && (
                      <div className="border-t border-slate-200 bg-slate-50/60 p-4 space-y-3">
                        {submissionsQuery.error && <p role="alert" className="text-sm text-rose-700">{getErrorMessage(submissionsQuery.error)}</p>}
                        <div className="overflow-x-auto bg-white border border-slate-200 rounded-lg">
                          <table className="w-full text-left text-sm">
                            <thead className="bg-slate-50 text-xs text-slate-500 border-b border-slate-200">
                              <tr>
                                <th className="px-3 py-2">Student</th>
                                <th className="px-3 py-2">Latest file</th>
                                <th className="px-3 py-2">Latest submission</th>
                                <th className="px-3 py-2">Attempts</th>
                                <th className="px-3 py-2">Status</th>
                                <th className="px-3 py-2 text-right">Actions</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {submissionsQuery.isLoading ? (
                                <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">Loading submissions...</td></tr>
                              ) : !submissions?.items.length ? (
                                <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">No student submissions.</td></tr>
                              ) : submissions.items.map((item) => {
                                const attemptsExpanded = expandedSubmissionId === item.submission_id;
                                return (
                                  <React.Fragment key={item.submission_id}>
                                    <tr>
                                      <td className="px-3 py-3">
                                        <p className="font-semibold text-slate-800">{item.student_display_name}</p>
                                        <p className="text-xs text-slate-500">{item.student_email}</p>
                                      </td>
                                      <td className="px-3 py-3 max-w-64">
                                        <p className="truncate font-medium text-slate-700" title={item.filename ?? undefined}>{item.filename ?? 'No file'}</p>
                                        {item.file_size_bytes && <p className="text-xs text-slate-500">{item.file_size_bytes.toLocaleString()} bytes</p>}
                                      </td>
                                      <td className="px-3 py-3 whitespace-nowrap text-xs text-slate-600">{item.submitted_at ? new Date(item.submitted_at).toLocaleString() : '—'}</td>
                                      <td className="px-3 py-3">
                                        <button
                                          type="button"
                                          aria-expanded={attemptsExpanded}
                                          aria-controls={`submission-attempts-${item.submission_id}`}
                                          onClick={() => setExpandedSubmissionId(attemptsExpanded ? undefined : item.submission_id)}
                                          className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-sky-200 bg-sky-50 text-sky-800 font-semibold"
                                        >
                                          {item.attempt_count}/{assignment.max_submissions}
                                          {attemptsExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                                        </button>
                                      </td>
                                      <td className="px-3 py-3"><span className="font-mono text-xs">{item.document_status ?? 'NO_DOCUMENT'}</span></td>
                                      <td className="px-3 py-3 text-right whitespace-nowrap">
                                        {item.document_version_id && (
                                          <button type="button" disabled={openingDocumentId === item.document_version_id} onClick={() => void openPdf(item.document_version_id!)} className="p-2 text-sky-700 hover:bg-sky-50 rounded-lg disabled:opacity-40" aria-label={`Open latest ${item.filename ?? 'PDF'}`}>
                                            <Download className="w-4 h-4" />
                                          </button>
                                        )}
                                        <button
                                          type="button"
                                          disabled={!item.document_status || !reviewableStatuses.includes(item.document_status)}
                                          onClick={() => onOpenSubmission(item.submission_id, item.document_status)}
                                          className="ml-1 px-3 py-2 bg-slate-900 text-white rounded-lg text-xs font-semibold disabled:opacity-40"
                                        >
                                          Review latest
                                        </button>
                                      </td>
                                    </tr>
                                    {attemptsExpanded && (
                                      <SubmissionAttemptHistory
                                        submissionId={item.submission_id}
                                        openingDocumentId={openingDocumentId}
                                        onOpenPdf={openPdf}
                                        onOpenResult={onOpenVersionResult}
                                      />
                                    )}
                                  </React.Fragment>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        <div className="flex items-center justify-between text-xs text-slate-600">
                          <span>{submissions?.total ?? 0} submissions · page {submissionPage} of {submissionPages}</span>
                          <div className="flex gap-2">
                            <button type="button" disabled={submissionPage <= 1 || submissionsQuery.isFetching} onClick={() => setSubmissionPage((page) => page - 1)} className="p-1.5 border border-slate-300 rounded disabled:opacity-40" aria-label="Previous submission page"><ChevronLeft className="w-4 h-4" /></button>
                            <button type="button" disabled={submissionPage >= submissionPages || submissionsQuery.isFetching} onClick={() => setSubmissionPage((page) => page + 1)} className="p-1.5 border border-slate-300 rounded disabled:opacity-40" aria-label="Next submission page"><ChevronRight className="w-4 h-4" /></button>
                          </div>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>
      ) : (
        <section id="course-panel-announcements" role="tabpanel" aria-labelledby="course-tab-announcements" className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Announcements</h2>
              <p className="text-xs text-slate-500 mt-0.5">Messages here are visible to enrolled students immediately.</p>
            </div>
            {course.status === 'ACTIVE' && !showAnnouncementForm && (
              <button type="button" onClick={() => startAnnouncement()} className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold">
                <Plus className="w-4 h-4" /> New announcement
              </button>
            )}
          </div>

          {showAnnouncementForm && (
            <form onSubmit={saveAnnouncement} className="bg-white border border-slate-200 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-bold text-slate-900">{editingAnnouncement ? 'Edit announcement' : 'New announcement'}</h3>
                <button type="button" onClick={() => { setShowAnnouncementForm(false); setEditingAnnouncement(undefined); setAnnouncementTitle(''); setAnnouncementBody(''); }} aria-label="Cancel announcement"><X className="w-4 h-4" /></button>
              </div>
              <label className="block text-sm text-slate-700">Title
                <input required maxLength={255} value={announcementTitle} onChange={(event) => setAnnouncementTitle(event.target.value)} className="block mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
              </label>
              <label className="block text-sm text-slate-700">Message
                <textarea required maxLength={10_000} rows={5} value={announcementBody} onChange={(event) => setAnnouncementBody(event.target.value)} className="block mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg" />
              </label>
              <button disabled={announcementSaving} className="px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-40">{announcementSaving ? 'Saving...' : 'Save announcement'}</button>
            </form>
          )}

          {loading ? (
            <p className="text-sm text-slate-500">Loading announcements...</p>
          ) : announcements.length === 0 ? (
            <p className="p-8 text-center border border-dashed border-slate-300 rounded-xl text-sm text-slate-500">No announcements yet.</p>
          ) : (
            <div className="space-y-3">
              {announcements.map((announcement) => (
                <article key={announcement.id} className="bg-white border border-slate-200 rounded-xl p-5">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="font-bold text-slate-900 flex items-center gap-2"><Bell className="w-4 h-4 text-sky-700" /> {announcement.title}</h3>
                      <p className="text-sm text-slate-700 mt-2 whitespace-pre-wrap">{announcement.body}</p>
                      <p className="text-xs text-slate-500 mt-3">Updated {new Date(announcement.updated_at).toLocaleString()}</p>
                    </div>
                    {course.status === 'ACTIVE' && (
                      <div className="flex gap-1 shrink-0">
                        <button type="button" onClick={() => startAnnouncement(announcement)} className="p-2 border border-slate-200 rounded-lg text-slate-600" aria-label={`Edit ${announcement.title}`}><Pencil className="w-4 h-4" /></button>
                        <button type="button" onClick={() => { if (window.confirm(`Delete announcement “${announcement.title}”?`)) void runAction(() => onDeleteAnnouncement(announcement.id)); }} className="p-2 border border-rose-200 rounded-lg text-rose-700" aria-label={`Delete ${announcement.title}`}><Trash2 className="w-4 h-4" /></button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {showAssignmentForm && (
        <AssignmentWizardModal
          assignment={editingAssignment}
          rubrics={rubrics}
          onClose={() => setShowAssignmentForm(false)}
          onSave={(input) => onSaveAssignment(input, editingAssignment?.id)}
        />
      )}
    </div>
  );
};
