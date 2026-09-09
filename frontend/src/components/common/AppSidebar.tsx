import React from 'react';
import {
  BookOpen,
  Inbox,
  GraduationCap,
  LogOut,
  FolderKanban,
  FileCheck2,
  Users,
  Settings2,
  Activity,
  Layers,
} from 'lucide-react';
import { UserRole } from '../../types/docgrading';

interface SidebarProps {
  activeRole: UserRole;
  onLogout: () => void;
  currentView: string;
  onSelectView: (view: string) => void;
  pendingReviewCount: number;
  appealCount: number;
}

export const AppSidebar: React.FC<SidebarProps> = ({
  activeRole,
  onLogout,
  currentView,
  onSelectView,
  pendingReviewCount,
  appealCount,
}) => {

  const roleLabels: Record<UserRole, string> = {
    teacher: 'Teacher',
    student: 'Student',
    admin: 'Admin',
  };

  return (
    <aside className="w-56 bg-white border-r border-[#DDE2E8] flex flex-col justify-between shrink-0 select-none h-screen sticky top-0">
      <div className="p-3">
        {/* Logo matching enterprise SaaS branding */}
        <div className="flex items-center gap-2.5 px-2 py-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-[#1F4B7A] text-white flex items-center justify-center shadow-2xs">
            <GraduationCap className="w-4 h-4" />
          </div>
          <span className="font-bold text-base tracking-tight text-[#172033]">
            DocGrading
          </span>
        </div>

        {/* Active workspace role */}
        <div className="mb-3.5 w-full h-9 px-3 bg-[#F3F5F7] border border-[#DDE2E8] rounded-lg text-xs font-semibold text-[#172033] flex items-center">
          {roleLabels[activeRole]}
        </div>

        {/* Navigation Items */}
        <div className="space-y-1">
          {activeRole === 'teacher' && (
            <>
              <button
                type="button"
                onClick={() => onSelectView('teacher_courses')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'teacher_courses' || currentView === 'teacher_workspace'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <BookOpen className="w-4 h-4 stroke-[1.75]" />
                <span>Courses</span>
              </button>

              <button
                type="button"
                onClick={() => onSelectView('teacher_queue')}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'teacher_queue' || currentView === 'teacher_review'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <div className="flex items-center gap-2.5 truncate">
                  <Inbox className="w-4 h-4 stroke-[1.75]" />
                  <span>Submission Queue</span>
                </div>
                {pendingReviewCount > 0 && (
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-[#FFF4E5] text-[#A65F13] border border-[#F6E1C5]">
                    {pendingReviewCount}
                  </span>
                )}
              </button>
            </>
          )}

          {activeRole === 'student' && (
            <>
              <button
                type="button"
                onClick={() => onSelectView('student_assignments')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'student_assignments'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <FolderKanban className="w-4 h-4 stroke-[1.75]" />
                <span>Assignments</span>
              </button>

              <button
                type="button"
                onClick={() => onSelectView('student_upload')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'student_upload'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <FileCheck2 className="w-4 h-4 stroke-[1.75]" />
                <span>Upload PDF</span>
              </button>

              <button
                type="button"
                onClick={() => onSelectView('student_status')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'student_status'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <Activity className="w-4 h-4 stroke-[1.75]" />
                <span>Submission Status</span>
              </button>
            </>
          )}

          {activeRole === 'admin' && (
            <>
              <button
                type="button"
                onClick={() => onSelectView('admin_dashboard')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'admin_dashboard'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <Layers className="w-4 h-4 stroke-[1.75]" />
                <span>Dashboard</span>
              </button>

              <button
                type="button"
                onClick={() => onSelectView('admin_users')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'admin_users'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <Users className="w-4 h-4 stroke-[1.75]" />
                <span>Users & Roles</span>
              </button>

              <button
                type="button"
                onClick={() => onSelectView('admin_rubrics')}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs transition-colors ${
                  currentView === 'admin_rubrics'
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] font-semibold border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033] font-medium'
                }`}
              >
                <Settings2 className="w-4 h-4 stroke-[1.75]" />
                <span>Rubric Standard</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* User profile at bottom */}
      <div className="p-3 border-t border-[#E9EDF2] flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-full bg-[#1F4B7A] text-white font-semibold text-xs flex items-center justify-center shrink-0 shadow-2xs">
            {activeRole === 'teacher' ? 'T' : activeRole === 'student' ? 'S' : 'A'}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-[#172033] truncate">
              {roleLabels[activeRole]}
            </p>
            <p className="text-[11px] text-[#8893A5] truncate">
              docgrading.edu.vn
            </p>
          </div>
        </div>

        <button
          type="button"
          title="Đăng xuất"
          onClick={onLogout}
          className="p-1.5 text-[#8893A5] hover:text-[#B53A3A] hover:bg-[#FCEEEE] rounded-lg transition-colors cursor-pointer"
        >
          <LogOut className="w-3.5 h-3.5" />
        </button>
      </div>
    </aside>
  );
};
