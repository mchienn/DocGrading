import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  KeyRound,
  CheckCircle2,
  Bell,
  ArrowRight,
  Loader2,
  Shield,
  Layers,
  FileCheck,
  FolderKanban,
  GraduationCap,
  Activity,
  History,
  Users,
  Settings2,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { WorkspaceRole } from '../../types/api';
import type { UserSession } from '../../types/auth';
import { AccountNav } from './AccountNav';

interface AccountSettingsViewProps {
  activeRole: WorkspaceRole;
  user: UserSession;
}

export const AccountSettingsView: React.FC<AccountSettingsViewProps> = ({
  activeRole,
  user,
}) => {
  const queryClient = useQueryClient();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [saving, setSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handlePasswordChange = async (event: React.FormEvent) => {
    event.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);

    if (newPassword.length < 12) {
      setErrorMsg('New password must be at least 12 characters long.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setErrorMsg('New password and confirmation do not match.');
      return;
    }

    setSaving(true);

    try {
      const updatedUser = await apiData(
        api.POST('/api/v1/auth/change-password', {
          body: {
            current_password: currentPassword,
            new_password: newPassword,
          },
        }),
      );

      queryClient.setQueryData(['session'], updatedUser);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setSuccessMsg('Password updated. Other sessions were signed out.');
    } catch (err) {
      setErrorMsg(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <AccountNav activeRole={activeRole} />
      <div className="p-4 sm:p-8 max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Account Settings</h1>
          <p className="text-sm text-[#596579] mt-1">
            Manage your password security, notifications, and workspace destinations.
          </p>
        </div>

        {/* Change Password Card */}
        <section
          aria-labelledby="password-settings-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6"
        >
          <div className="flex items-center gap-2 mb-1">
            <KeyRound className="w-4 h-4 text-[#1F4B7A]" />
            <h2 id="password-settings-title" className="text-base font-bold text-slate-900">
              Change Password
            </h2>
          </div>
          <p className="text-xs text-[#596579] mb-4">
            Enter your current password followed by a new password of at least 12 characters.
          </p>

          <form onSubmit={handlePasswordChange} className="space-y-4 max-w-md">
            {successMsg && (
              <div
                role="status"
                className="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{successMsg}</span>
              </div>
            )}

            {errorMsg && (
              <div
                role="alert"
                className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs"
              >
                {errorMsg}
              </div>
            )}

            <div>
              <label
                htmlFor="current-password"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Current Password
              </label>
              <input
                id="current-password"
                name="current_password"
                type="password"
                required
                autoComplete="current-password"
                disabled={saving}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-900 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A] disabled:opacity-50"
              />
            </div>

            <div>
              <label
                htmlFor="new-password"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                New Password (minimum 12 characters)
              </label>
              <input
                id="new-password"
                name="new_password"
                type="password"
                required
                minLength={12}
                autoComplete="new-password"
                disabled={saving}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-900 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A] disabled:opacity-50"
              />
            </div>

            <div>
              <label
                htmlFor="confirm-password"
                className="block text-xs font-semibold text-slate-700 mb-1"
              >
                Confirm New Password
              </label>
              <input
                id="confirm-password"
                name="confirm_password"
                type="password"
                required
                minLength={12}
                autoComplete="new-password"
                disabled={saving}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-900 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A] disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={saving || !currentPassword || !newPassword || !confirmPassword}
              className="inline-flex items-center justify-center px-4 py-2 bg-[#1F4B7A] hover:bg-[#163657] text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  <span>Updating password...</span>
                </>
              ) : (
                'Update password'
              )}
            </button>
          </form>
        </section>

        {/* Notifications Delivery Info */}
        <section
          aria-labelledby="notifications-settings-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-3"
        >
          <div className="flex items-center gap-2">
            <Bell className="w-4 h-4 text-[#1F4B7A]" />
            <h2 id="notifications-settings-title" className="text-base font-bold text-slate-900">
              Notification Delivery
            </h2>
          </div>
          <p className="text-xs text-[#596579] leading-relaxed">
            DocGrading provides in-app polling notifications for grading updates, review request
            resolutions, and processing statuses. All active updates are accessible through the
            top header bell or the full notifications page.
          </p>
          <div className="pt-1">
            <Link
              to={`/${activeRole}/notifications`}
              className="inline-flex items-center gap-1 text-xs font-semibold text-[#1F4B7A] hover:underline"
            >
              <span>Go to full notifications manager</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </section>

        {/* Role Quick Links */}
        <section
          aria-labelledby="workspace-links-title"
          className="bg-white border border-[#DDE2E8] rounded-xl p-5 sm:p-6 space-y-4"
        >
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-[#1F4B7A]" />
            <h2 id="workspace-links-title" className="text-base font-bold text-slate-900">
              Workspace Operations
            </h2>
          </div>
          <p className="text-xs text-[#596579]">
            Quick navigation to primary functions in your assigned {activeRole} workspace.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            {activeRole === 'admin' && (
              <>
                <Link
                  to="/admin/dashboard"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Activity className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Platform Analysis</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/admin/jobs"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Activity className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Job Monitoring</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/admin/users"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Users className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">User Management</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/admin/audit"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <History className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Audit Trail</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>
              </>
            )}

            {activeRole === 'teacher' && (
              <>
                <Link
                  to="/teacher/courses"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Layers className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Course Workspace</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/teacher/rubrics"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Settings2 className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Rubric Templates</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/teacher/appeals"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <FileCheck className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Review Appeals</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>
              </>
            )}

            {activeRole === 'student' && (
              <>
                <Link
                  to="/student/assignments"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <FolderKanban className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">My Assignments</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>

                <Link
                  to="/student/join"
                  className="p-3.5 border border-[#DDE2E8] rounded-lg hover:border-[#1F4B7A] hover:bg-[#F5F7FA] transition-colors flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <GraduationCap className="w-4 h-4 text-[#1F4B7A]" />
                    <span className="text-xs font-semibold text-slate-900">Join a Course</span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                </Link>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
