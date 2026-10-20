import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  User,
  Mail,
  Shield,
  Calendar,
  CheckCircle2,
  BookOpen,
  ArrowRight,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';
import type { WorkspaceRole } from '../../types/api';
import type { UserSession } from '../../types/auth';
import { AccountNav } from './AccountNav';

type CourseItem = components['schemas']['CourseResponse'];

interface AccountProfileViewProps {
  activeRole: WorkspaceRole;
  user: UserSession;
}

export const AccountProfileView: React.FC<AccountProfileViewProps> = ({
  activeRole,
  user,
}) => {
  const queryClient = useQueryClient();
  const [displayNameInput, setDisplayNameInput] = useState(user.display_name);
  const [savedDisplayName, setSavedDisplayName] = useState(user.display_name);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Accessible courses for Teacher / Student
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
    enabled: activeRole === 'teacher' || activeRole === 'student',
  });

  const handleUpdateDisplayName = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = displayNameInput.trim();
    if (!trimmed) {
      setSaveError('Display name cannot be empty.');
      setSaveSuccess(false);
      return;
    }

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);

    try {
      const updatedUser = await apiData(
        api.PATCH('/api/v1/auth/me', {
          params: {
            header: {
              'If-Match': `"rev-${user.revision}"`,
            },
          },
          body: {
            display_name: trimmed,
          },
        }),
      );

      queryClient.setQueryData(['session'], updatedUser);
      setDisplayNameInput(updatedUser.display_name);
      setSavedDisplayName(updatedUser.display_name);
      setSaveSuccess(true);
    } catch (err) {
      setSaveError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const memberSince = user.created_at
    ? new Date(user.created_at).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : '—';

  return (
    <div>
      <AccountNav activeRole={activeRole} />
      <div className="p-4 sm:p-8 max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Account Profile</h1>
          <p className="text-sm text-[#596579] mt-1">
            Manage your personal profile and account credentials.
          </p>
        </div>

        {/* Account Details Card */}
        <section
          aria-labelledby="account-info-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4"
        >
          <h2 id="account-info-title" className="text-base font-bold text-slate-900">
            Account Details
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div className="p-3.5 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#8893A5] uppercase tracking-wider mb-1">
                <Mail className="w-3.5 h-3.5" />
                <span>Email Address</span>
              </div>
              <p className="font-medium text-slate-900 break-all">{user.email}</p>
              <p className="text-[11px] text-[#8893A5] mt-0.5">Read-only account identifier</p>
            </div>

            <div className="p-3.5 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#8893A5] uppercase tracking-wider mb-1">
                <Shield className="w-3.5 h-3.5" />
                <span>Account Status</span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                    user.status === 'ACTIVE'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : 'bg-rose-50 text-rose-700 border border-rose-200'
                  }`}
                >
                  {user.status}
                </span>
                <span className="text-xs text-[#8893A5]">rev-{user.revision}</span>
              </div>
            </div>

            <div className="p-3.5 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#8893A5] uppercase tracking-wider mb-1">
                <User className="w-3.5 h-3.5" />
                <span>Assigned Roles</span>
              </div>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {user.roles.map((role) => (
                  <span
                    key={role}
                    className="px-2 py-0.5 bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0] rounded text-xs font-semibold"
                  >
                    {role}
                  </span>
                ))}
              </div>
            </div>

            <div className="p-3.5 bg-[#F5F7FA] border border-[#DDE2E8] rounded-lg">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#8893A5] uppercase tracking-wider mb-1">
                <Calendar className="w-3.5 h-3.5" />
                <span>Member Since</span>
              </div>
              <p className="font-medium text-slate-900">{memberSince}</p>
            </div>
          </div>
        </section>

        {/* Edit Display Name Form */}
        <section
          aria-labelledby="edit-profile-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6"
        >
          <h2 id="edit-profile-title" className="text-base font-bold text-slate-900 mb-1">
            Display Name
          </h2>
          <p className="text-xs text-[#596579] mb-4">
            This name will be shown across courses, submissions, and review requests.
          </p>

          <form onSubmit={handleUpdateDisplayName} className="space-y-4 max-w-lg">
            {saveSuccess && (
              <div
                role="status"
                className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>Display name updated successfully.</span>
              </div>
            )}

            {saveError && (
              <div
                role="alert"
                className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs"
              >
                {saveError}
              </div>
            )}

            <div>
              <label htmlFor="display_name" className="block text-xs font-semibold text-slate-700 mb-1">
                Display Name
              </label>
              <input
                id="display_name"
                name="display_name"
                type="text"
                required
                maxLength={255}
                disabled={saving}
                value={displayNameInput}
                onChange={(e) => setDisplayNameInput(e.target.value)}
                className="block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-900 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A] disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={saving || displayNameInput.trim() === savedDisplayName}
              className="inline-flex items-center justify-center px-4 py-2 bg-[#1F4B7A] hover:bg-[#163657] text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                'Save changes'
              )}
            </button>
          </form>
        </section>

        {/* Role Summary Section */}
        <section
          aria-labelledby="role-summary-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4"
        >
          <div className="flex items-center justify-between">
            <div>
              <h2 id="role-summary-title" className="text-base font-bold text-slate-900">
                Workspace Overview
              </h2>
              <p className="text-xs text-[#596579] mt-0.5">
                Overview of your permissions and assigned workspace content.
              </p>
            </div>
          </div>

          {activeRole === 'admin' ? (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
              <Link
                to="/admin/users"
                className="p-4 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors group flex flex-col justify-between"
              >
                <div>
                  <h3 className="font-semibold text-sm text-slate-900 group-hover:text-[#1F4B7A]">
                    User Management
                  </h3>
                  <p className="text-xs text-[#596579] mt-1">
                    Manage system users, roles, and status.
                  </p>
                </div>
                <span className="inline-flex items-center text-xs font-semibold text-[#1F4B7A] mt-3">
                  Open Users <ArrowRight className="w-3.5 h-3.5 ml-1" />
                </span>
              </Link>

              <Link
                to="/admin/dashboard"
                className="p-4 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors group flex flex-col justify-between"
              >
                <div>
                  <h3 className="font-semibold text-sm text-slate-900 group-hover:text-[#1F4B7A]">
                    Analysis Dashboard
                  </h3>
                  <p className="text-xs text-[#596579] mt-1">
                    System operations metrics and analytics.
                  </p>
                </div>
                <span className="inline-flex items-center text-xs font-semibold text-[#1F4B7A] mt-3">
                  Open Analysis <ArrowRight className="w-3.5 h-3.5 ml-1" />
                </span>
              </Link>

              <Link
                to="/admin/audit"
                className="p-4 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors group flex flex-col justify-between"
              >
                <div>
                  <h3 className="font-semibold text-sm text-slate-900 group-hover:text-[#1F4B7A]">
                    Audit Trail
                  </h3>
                  <p className="text-xs text-[#596579] mt-1">
                    Inspect recorded administrative actions.
                  </p>
                </div>
                <span className="inline-flex items-center text-xs font-semibold text-[#1F4B7A] mt-3">
                  Open Audit Log <ArrowRight className="w-3.5 h-3.5 ml-1" />
                </span>
              </Link>
            </div>
          ) : (
            <div>
              {coursesQuery.isLoading ? (
                <div className="p-8 text-center text-slate-400 flex flex-col items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-[#1F4B7A]" />
                  <span className="text-sm">Loading course enrollments...</span>
                </div>
              ) : coursesQuery.isError ? (
                <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm flex items-center justify-between">
                  <span>Failed to load courses: {getErrorMessage(coursesQuery.error)}</span>
                  <button
                    type="button"
                    onClick={() => void coursesQuery.refetch()}
                    className="inline-flex items-center gap-1 font-semibold text-[#1F4B7A] hover:underline"
                  >
                    <RefreshCw className="w-3.5 h-3.5" /> Retry
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs text-[#596579]">
                    <span>
                      {(coursesQuery.data ?? []).length} accessible course{coursesQuery.data?.length === 1 ? '' : 's'}
                    </span>
                    <Link
                      to={activeRole === 'teacher' ? '/teacher/courses' : '/student/assignments'}
                      className="font-semibold text-[#1F4B7A] hover:underline inline-flex items-center gap-1"
                    >
                      {activeRole === 'teacher' ? 'View all courses' : 'View assignments'}
                      <ArrowRight className="w-3 h-3" />
                    </Link>
                  </div>

                  {(coursesQuery.data ?? []).length === 0 ? (
                    <div className="p-6 text-center text-slate-400 border border-dashed border-slate-200 rounded-lg">
                      <BookOpen className="w-6 h-6 mx-auto mb-1 text-slate-300" />
                      <p className="text-xs font-medium text-slate-600">No active course memberships</p>
                      {activeRole === 'student' && (
                        <Link
                          to="/student/join"
                          className="mt-2 inline-block text-xs font-semibold text-[#1F4B7A] hover:underline"
                        >
                          Join a course with code
                        </Link>
                      )}
                    </div>
                  ) : (
                    <div className="divide-y divide-slate-100 border border-[#DDE2E8] rounded-lg overflow-hidden">
                      {(coursesQuery.data ?? []).slice(0, 5).map((course: CourseItem) => (
                        <div
                          key={course.id}
                          className="p-3 flex items-center justify-between gap-3 hover:bg-slate-50 transition-colors"
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-xs text-slate-900 truncate">
                                {course.code}
                              </span>
                              <span className="text-xs text-[#596579] truncate">{course.name}</span>
                            </div>
                            <span className="text-[11px] text-[#8893A5]">{course.term}</span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span
                              className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                                course.status === 'ACTIVE'
                                  ? 'bg-emerald-50 text-emerald-700'
                                  : 'bg-slate-100 text-slate-600'
                              }`}
                            >
                              {course.status}
                            </span>
                            {activeRole === 'teacher' && (
                              <Link
                                to={`/teacher/courses/${course.id}`}
                                className="text-xs font-semibold text-[#1F4B7A] hover:underline"
                              >
                                Manage
                              </Link>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
};
