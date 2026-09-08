import React, { useState } from 'react';
import { Bell, ChevronRight, CheckCircle2, Clock } from 'lucide-react';
import { UserRole } from '../../types/docgrading';

interface AppHeaderProps {
  activeRole: UserRole;
  currentView: string;
  courseTitle?: string;
  assignmentTitle?: string;
  onNavigateBreadcrumb?: (view: string) => void;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  activeRole,
  currentView,
  courseTitle,
  onNavigateBreadcrumb,
}) => {
  const [showNotifications, setShowNotifications] = useState(false);

  const roleLabels: Record<UserRole, string> = {
    teacher: 'Teacher',
    student: 'Student',
    admin: 'Admin',
  };

  const getViewLabel = () => {
    switch (currentView) {
      case 'teacher_courses':
        return 'Courses';
      case 'teacher_workspace':
        return courseTitle ? courseTitle : 'Course Workspace';
      case 'teacher_queue':
        return 'Submission Queue';
      case 'teacher_review':
        return 'Grading Workspace';
      case 'teacher_appeals':
        return 'Appeals';
      case 'student_assignments':
        return 'Courses & Assignments';
      case 'student_upload':
        return 'Upload PDF';
      case 'student_status':
        return 'Submission Status';
      case 'student_result':
        return 'Published Results';
      case 'admin_dashboard':
        return 'Dashboard';
      case 'admin_users':
        return 'Users';
      case 'admin_rubrics':
        return 'Rubric Standards';
      default:
        return 'Courses';
    }
  };

  return (
    <header className="h-14 bg-white border-b border-[#DDE2E8] px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Breadcrumb matching enterprise navigation */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[#8893A5] font-normal">{roleLabels[activeRole]}</span>
        <ChevronRight className="w-3.5 h-3.5 text-[#CBD5E1]" />
        {currentView === 'teacher_workspace' ? (
          <>
            <button
              type="button"
              onClick={() => onNavigateBreadcrumb?.('teacher_courses')}
              className="text-[#596579] hover:text-[#1F4B7A] font-normal transition-colors cursor-pointer"
            >
              Courses
            </button>
            <ChevronRight className="w-3.5 h-3.5 text-[#CBD5E1]" />
            <span className="text-[#172033] font-semibold">{courseTitle || 'Workspace'}</span>
          </>
        ) : (
          <span className="text-[#172033] font-semibold">{getViewLabel()}</span>
        )}
      </div>

      {/* Right side: Bell icon with notification dot */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setShowNotifications(!showNotifications)}
          className="relative p-2 text-[#596579] hover:text-[#172033] hover:bg-[#F3F5F7] rounded-lg transition-colors cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)]"
          aria-label="Thông báo"
        >
          <Bell className="w-4 h-4 stroke-[1.75]" />
          <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-[#B53A3A] ring-2 ring-white"></span>
        </button>

        {showNotifications && (
          <div className="absolute right-0 mt-2 w-80 bg-white rounded-xl shadow-[0_8px_24px_rgba(16,24,40,0.12)] border border-[#DDE2E8] p-4 z-50 text-xs">
            <div className="flex items-center justify-between pb-2.5 border-b border-[#E9EDF2]">
              <span className="font-semibold text-[#172033]">Notifications</span>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-[#EAF1F8] text-[#1F4B7A]">2 new</span>
            </div>
            <div className="divide-y divide-[#E9EDF2] mt-2">
              <div className="py-2.5 flex items-start gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-[#237A57] shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-[#172033]">
                    6 bài nộp mới trong lớp INT2208-01
                  </p>
                  <p className="text-[11px] text-[#8893A5] mt-0.5">15 phút trước</p>
                </div>
              </div>
              <div className="py-2.5 flex items-start gap-2.5">
                <Clock className="w-4 h-4 text-[#A65F13] shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-[#172033]">
                    5 bài nộp khóa luận tốt nghiệp cần duyệt
                  </p>
                  <p className="text-[11px] text-[#8893A5] mt-0.5">1 giờ trước</p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};
