import React from 'react';
import { BookOpen, GraduationCap, LogOut, Settings2, FolderKanban } from 'lucide-react';
import type { WorkspaceRole } from '../../types/api';

interface SidebarProps {
  activeRole: WorkspaceRole;
  displayName: string;
  currentPath: string;
  onNavigate: (path: string) => void;
  onLogout: () => void;
}

const roleLabels: Record<WorkspaceRole, string> = {
  teacher: 'Teacher',
  student: 'Student',
  admin: 'Admin',
};

export const AppSidebar: React.FC<SidebarProps> = ({
  activeRole,
  displayName,
  currentPath,
  onNavigate,
  onLogout,
}) => {
  const navItems = activeRole === 'student'
    ? [{ path: '/student/assignments', label: 'Assignments', icon: FolderKanban }]
    : [
        { path: `/${activeRole}/courses`, label: 'Courses', icon: BookOpen },
        { path: `/${activeRole}/rubrics`, label: 'Rubrics', icon: Settings2 },
      ];

  return (
    <aside className="w-56 bg-white border-r border-[#DDE2E8] flex flex-col justify-between shrink-0 h-screen sticky top-0">
      <div className="p-3">
        <div className="flex items-center gap-2.5 px-2 py-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-[#1F4B7A] text-white flex items-center justify-center">
            <GraduationCap className="w-4 h-4" />
          </div>
          <span className="font-bold text-base text-[#172033]">DocGrading</span>
        </div>
        <div className="mb-4 px-3 py-2 bg-[#F3F5F7] border border-[#DDE2E8] rounded-lg">
          <p className="text-xs font-semibold text-[#172033] truncate">{displayName}</p>
          <p className="text-[11px] text-[#8893A5]">{roleLabels[activeRole]}</p>
        </div>
        <nav className="space-y-1">
          {navItems.map(({ path, label, icon: Icon }) => {
            const active = currentPath.startsWith(path);
            return (
              <button
                key={path}
                type="button"
                onClick={() => onNavigate(path)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  active
                    ? 'bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0]'
                    : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033]'
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>
      </div>
      <div className="p-3 border-t border-[#E9EDF2] flex items-center justify-between gap-2">
        <span className="text-xs text-[#596579] truncate">{displayName}</span>
        <button
          type="button"
          aria-label="Log out"
          title="Log out"
          onClick={onLogout}
          className="p-2 text-[#8893A5] hover:text-[#B53A3A] hover:bg-[#FCEEEE] rounded-lg"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );
};
