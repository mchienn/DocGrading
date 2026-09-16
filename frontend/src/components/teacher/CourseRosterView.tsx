import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus, UserMinus, UserPlus } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import type { components } from '../../api/schema';
import { api, apiData, apiVoid, getErrorMessage } from '../../api/client';
import { CourseJoinCodeSection } from './CourseJoinCodeSection';

type MembershipStatus = components['schemas']['MembershipStatus'];
type CourseMember = components['schemas']['CourseMemberResponse'];

const inputClass = 'block mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm';

const AddMemberModal: React.FC<{
  courseId: string;
  onClose: () => void;
  onSuccess: (outcomeMessage: string) => void;
}> = ({ courseId, onClose, onSuccess }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const email = String(fields.get('email') ?? '').trim().toLowerCase();
    const reason = String(fields.get('reason') ?? '').trim() || undefined;

    if (!email) {
      setError('Email is required.');
      return;
    }

    setError(undefined);
    setSubmitting(true);
    try {
      const response = await apiData(api.POST('/api/v1/courses/{course_id}/members', {
        params: { path: { course_id: courseId } },
        body: { email, reason },
      }));

      form.reset();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['course-members', courseId] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);

      let message = `Added ${email} to course roster.`;
      if (response.outcome === 'REACTIVATED') {
        message = `Reactivated membership for ${email}.`;
      } else if (response.outcome === 'INVITED') {
        message = `Pending invite created for ${email}.`;
      }

      onSuccess(message);
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="add-member-title"
      onCancel={(event) => {
        if (submitting) event.preventDefault();
      }}
      onClose={onClose}
      className="m-auto w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl backdrop:bg-slate-900/50"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-center gap-2">
          <UserPlus className="w-5 h-5 text-[#1F4B7A]" />
          <h2 id="add-member-title" className="font-bold text-lg text-slate-900">Add student to course</h2>
        </div>
        {error && <p role="alert" className="text-sm text-rose-700 bg-rose-50 p-2.5 rounded-lg border border-rose-200">{error}</p>}
        <fieldset disabled={submitting} className="space-y-3">
          <label className="block text-sm font-medium text-slate-700">
            Student email
            <input
              autoFocus
              required
              name="email"
              type="email"
              maxLength={320}
              placeholder="student@example.edu"
              autoComplete="off"
              className={inputClass}
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Reason (optional)
            <textarea
              name="reason"
              maxLength={1000}
              rows={3}
              placeholder="e.g. Late enrollment approval"
              className={inputClass}
            />
          </label>
          <p className="text-xs text-slate-500">
            If a student account exists, membership starts immediately. Otherwise, a pending invite is created.
          </p>
        </fieldset>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="px-4 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold disabled:opacity-40"
          >
            {submitting ? 'Adding...' : 'Add student'}
          </button>
        </div>
      </form>
    </dialog>
  );
};

const RemoveMemberModal: React.FC<{
  courseId: string;
  member: CourseMember;
  onClose: () => void;
  onSuccess: (outcomeMessage: string) => void;
}> = ({ courseId, member, onClose, onSuccess }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const reason = String(fields.get('reason') ?? '').trim() || undefined;

    setError(undefined);
    setSubmitting(true);
    try {
      await apiVoid(api.DELETE('/api/v1/courses/{course_id}/members/{user_id}', {
        params: {
          path: { course_id: courseId, user_id: member.user_id },
        },
        body: { reason },
      }));

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['course-members', courseId] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);

      onSuccess(`Removed ${member.display_name} from course roster.`);
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="remove-member-title"
      onCancel={(event) => {
        if (submitting) event.preventDefault();
      }}
      onClose={onClose}
      className="m-auto w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl backdrop:bg-slate-900/50"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-center gap-2">
          <UserMinus className="w-5 h-5 text-rose-600" />
          <h2 id="remove-member-title" className="font-bold text-lg text-slate-900">Remove student from course</h2>
        </div>
        <p className="text-sm text-slate-600">
          Are you sure you want to remove <strong className="text-slate-900">{member.display_name}</strong> (<span className="text-slate-500">{member.email}</span>) from this course?
        </p>
        {error && <p role="alert" className="text-sm text-rose-700 bg-rose-50 p-2.5 rounded-lg border border-rose-200">{error}</p>}
        <fieldset disabled={submitting} className="space-y-3">
          <label className="block text-sm font-medium text-slate-700">
            Reason (optional)
            <textarea
              name="reason"
              maxLength={1000}
              rows={3}
              placeholder="e.g. Dropped course"
              className={inputClass}
            />
          </label>
        </fieldset>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="px-4 py-2 border border-slate-300 rounded-lg text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-rose-600 text-white rounded-lg text-sm font-semibold hover:bg-rose-700 disabled:opacity-40"
          >
            {submitting ? 'Removing...' : 'Confirm removal'}
          </button>
        </div>
      </form>
    </dialog>
  );
};

export const CourseRosterView: React.FC<{ role: 'teacher' | 'admin' }> = ({ role }) => {
  const { courseId = '' } = useParams();
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<MembershipStatus | ''>('');
  const [page, setPage] = useState(1);
  const [statusNotice, setStatusNotice] = useState<string>();
  const [showAddModal, setShowAddModal] = useState(false);
  const [memberToRemove, setMemberToRemove] = useState<CourseMember | null>(null);

  const courseQuery = useQuery({
    queryKey: ['course', courseId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}', {
      params: { path: { course_id: courseId } },
    })),
    enabled: Boolean(courseId),
  });

  const membersQuery = useQuery({
    queryKey: ['course-members', courseId, statusFilter, page],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/members', {
      params: {
        path: { course_id: courseId },
        query: {
          status: statusFilter || undefined,
          page,
          page_size: 50,
        },
      },
    })),
    enabled: Boolean(courseId),
  });

  const course = courseQuery.data;
  const isArchived = course?.status === 'ARCHIVED';
  const total = membersQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 50));

  return (
    <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
      <button
        type="button"
        onClick={() => navigate(`/${role}/courses/${courseId}`)}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" /> Back to course
      </button>

      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          {course && <span className="font-mono text-xs font-bold text-sky-700">{course.code}</span>}
          <h1 className="text-2xl font-bold text-slate-900 mt-1">
            {course ? `${course.name} · Roster` : 'Course Roster'}
          </h1>
          {course && (
            <p className="text-sm text-slate-500 mt-1">
              {course.term} · {course.status}
            </p>
          )}
        </div>
        {!isArchived && course?.status === 'ACTIVE' && (
          <button
            type="button"
            onClick={() => {
              setStatusNotice(undefined);
              setShowAddModal(true);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 bg-[#1F4B7A] text-white rounded-lg text-sm font-semibold self-start"
          >
            <Plus className="w-4 h-4" /> Add student
          </button>
        )}
      </div>

      {isArchived && (
        <div className="p-3.5 rounded-xl border border-amber-200 bg-amber-50 text-amber-900 text-sm font-medium">
          This course is archived. Roster is read-only.
        </div>
      )}

      {statusNotice && (
        <div role="status" className="p-3 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 text-sm font-medium flex items-center justify-between">
          <span>{statusNotice}</span>
          <button type="button" onClick={() => setStatusNotice(undefined)} className="text-xs font-semibold text-emerald-700 hover:text-emerald-900">Dismiss</button>
        </div>
      )}

      {courseQuery.error && (
        <p role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {getErrorMessage(courseQuery.error)}
        </p>
      )}

      <CourseJoinCodeSection courseId={courseId} isArchived={isArchived} />

      <section aria-label="Roster filters" className="flex flex-wrap items-center justify-between gap-4 p-4 bg-white border border-slate-200 rounded-xl">
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-slate-700 flex items-center gap-2">
            Status filter
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as MembershipStatus | '');
                setPage(1);
              }}
              className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm bg-white"
            >
              <option value="">ALL</option>
              <option value="ACTIVE">ACTIVE</option>
              <option value="REMOVED">REMOVED</option>
            </select>
          </label>
        </div>
        <button
          type="button"
          disabled={membersQuery.isFetching}
          onClick={() => void membersQuery.refetch()}
          className="px-3 py-1.5 border border-slate-200 rounded-lg text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
        >
          Refresh
        </button>
      </section>

      {membersQuery.error && (
        <p role="alert" className="p-3 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 text-sm">
          {getErrorMessage(membersQuery.error)}
        </p>
      )}

      {membersQuery.isLoading ? (
        <p role="status" className="p-8 text-center text-sm text-slate-500">Loading roster...</p>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold">
              <tr>
                <th scope="col" className="p-4">Student</th>
                <th scope="col" className="p-4">Status</th>
                <th scope="col" className="p-4">Joined</th>
                <th scope="col" className="p-4">Source</th>
                <th scope="col" className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {membersQuery.data?.items.map((member) => (
                <tr key={member.id} className="hover:bg-slate-50/60">
                  <td className="p-4">
                    <p className="font-semibold text-slate-900">{member.display_name}</p>
                    <p className="text-xs text-slate-500">{member.email}</p>
                  </td>
                  <td className="p-4">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                        member.status === 'ACTIVE'
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                          : 'bg-slate-100 text-slate-600 border border-slate-200'
                      }`}
                    >
                      {member.status}
                    </span>
                  </td>
                  <td className="p-4 text-slate-600">
                    {new Date(member.joined_at).toLocaleString()}
                  </td>
                  <td className="p-4 text-slate-600">
                    <span className="font-mono text-xs font-semibold px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                      {member.joined_via}
                    </span>
                  </td>
                  <td className="p-4 text-right">
                    {!isArchived && member.status === 'ACTIVE' ? (
                      <button
                        type="button"
                        onClick={() => {
                          setStatusNotice(undefined);
                          setMemberToRemove(member);
                        }}
                        className="px-3 py-1.5 border border-rose-200 text-rose-700 hover:bg-rose-50 rounded-lg text-xs font-semibold"
                      >
                        Remove
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {membersQuery.data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-slate-500">
                    No members match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-slate-600">
        <span>
          {total} {total === 1 ? 'member' : 'members'} · page {page} of {totalPages}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            aria-label="Previous page"
            disabled={page <= 1 || membersQuery.isFetching}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="px-3 py-1.5 border border-slate-200 bg-white rounded-lg disabled:opacity-40 hover:bg-slate-50 font-medium"
          >
            Previous
          </button>
          <button
            type="button"
            aria-label="Next page"
            disabled={page >= totalPages || membersQuery.isFetching}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 border border-slate-200 bg-white rounded-lg disabled:opacity-40 hover:bg-slate-50 font-medium"
          >
            Next
          </button>
        </div>
      </div>

      {showAddModal && (
        <AddMemberModal
          courseId={courseId}
          onClose={() => setShowAddModal(false)}
          onSuccess={(msg) => {
            setPage(1);
            setStatusNotice(msg);
          }}
        />
      )}

      {memberToRemove && (
        <RemoveMemberModal
          courseId={courseId}
          member={memberToRemove}
          onClose={() => setMemberToRemove(null)}
          onSuccess={(msg) => {
            setPage(1);
            setStatusNotice(msg);
          }}
        />
      )}
    </div>
  );
};
