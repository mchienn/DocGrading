import React from 'react';
import {
  BookOpen,
  GraduationCap,
  LogOut,
  Settings2,
  FolderKanban,
  LayoutDashboard,
  Users,
  Activity,
  History,
  MessageSquare,
  User,
  Bell,
  FileText,
  Settings,
  Cpu,
} from 'lucide-react';
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
  const workspaceItems =
    activeRole === 'student'
      ? [
          { path: '/student/assignments', label: 'Assignments', icon: FolderKanban },
          { path: '/student/join', label: 'Join course', icon: GraduationCap },
        ]
      : [
          ...(activeRole === 'admin'
            ? [
                { path: '/admin/dashboard', label: 'Dashboard', icon: LayoutDashboard },
                { path: '/admin/users', label: 'Users', icon: Users },
                { path: '/admin/jobs', label: 'Analysis jobs', icon: Activity },
                { path: '/admin/audit', label: 'Audit trail', icon: History },
                { path: '/admin/ai-providers', label: 'AI providers', icon: Cpu },
              ]
            : []),
          { path: `/${activeRole}/courses`, label: 'Courses', icon: BookOpen },
          { path: `/${activeRole}/rubrics`, label: 'Rubrics', icon: Settings2 },
          { path: `/${activeRole}/appeals`, label: 'Appeals', icon: MessageSquare },
        ];

  const accountItems = [
    { path: `/${activeRole}/profile`, label: 'Profile', icon: User },
    { path: `/${activeRole}/notifications`, label: 'Notifications', icon: Bell },
    { path: `/${activeRole}/files`, label: 'Files', icon: FileText },
    { path: `/${activeRole}/settings`, label: 'Settings', icon: Settings },
  ];

  return (
    <aside className="w-16 sm:w-56 bg-white border-r border-[#DDE2E8] flex flex-col justify-between shrink-0 h-screen sticky top-0">
      <div className="p-2 sm:p-3 overflow-y-auto flex-1">
        {/* Brand */}
        <div className="flex items-center justify-center sm:justify-start gap-2.5 px-2 py-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-[#1F4B7A] text-white flex items-center justify-center shrink-0">
            <GraduationCap className="w-4 h-4" />
          </div>
          <span className="hidden sm:inline font-bold text-base text-[#172033]">DocGrading</span>
        </div>

        {/* User Card button navigating to Profile */}
        <button
          type="button"
          onClick={() => onNavigate(`/${activeRole}/profile`)}
          title="View account profile"
          className="w-full text-left hidden sm:block mb-4 px-3 py-2 bg-[#F3F5F7] hover:bg-[#EAF1F8] border border-[#DDE2E8] hover:border-[#D3E2F0] rounded-lg transition-colors group cursor-pointer"
        >
          <p className="text-xs font-semibold text-[#172033] group-hover:text-[#1F4B7A] truncate">
            {displayName}
          </p>
          <p className="text-[11px] text-[#8893A5]">{roleLabels[activeRole]}</p>
        </button>

        {/* Workspace Navigation */}
        <div className="space-y-1">
          <p className="hidden sm:block px-3 py-1 text-[10px] font-bold text-[#8893A5] uppercase tracking-wider">
            Workspace
          </p>
          <nav aria-label="Workspace navigation" className="space-y-0.5">
            {workspaceItems.map(({ path, label, icon: Icon }) => {
              const active = currentPath.startsWith(path);
              return (
                <button
                  key={path}
                  type="button"
                  onClick={() => onNavigate(path)}
                  aria-label={label}
                  aria-current={active ? 'page' : undefined}
                  title={label}
                  className={`w-full flex items-center justify-center sm:justify-start gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    active
                      ? 'bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0]'
                      : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033]'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="hidden sm:inline truncate">{label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Grouped Account Navigation */}
        <div className="mt-4 pt-3 border-t border-[#E9EDF2] space-y-1">
          <p className="hidden sm:block px-3 py-1 text-[10px] font-bold text-[#8893A5] uppercase tracking-wider">
            Account
          </p>
          <nav aria-label="Account navigation" className="space-y-0.5">
            {accountItems.map(({ path, label, icon: Icon }) => {
              const active = currentPath.startsWith(path);
              return (
                <button
                  key={path}
                  type="button"
                  onClick={() => onNavigate(path)}
                  aria-label={label}
                  aria-current={active ? 'page' : undefined}
                  title={label}
                  className={`w-full flex items-center justify-center sm:justify-start gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    active
                      ? 'bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0]'
                      : 'text-[#596579] hover:bg-[#F3F5F7] hover:text-[#172033]'
                  }`}
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="hidden sm:inline truncate">{label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Footer / Logout */}
      <div className="p-2 sm:p-3 border-t border-[#E9EDF2] flex items-center justify-center sm:justify-between gap-2 shrink-0 bg-white">
        <button
          type="button"
          onClick={() => onNavigate(`/${activeRole}/profile`)}
          title="Account profile"
          className="hidden sm:inline text-xs text-[#596579] hover:text-[#1F4B7A] truncate text-left cursor-pointer"
        >
          {displayName}
        </button>
        <button
          type="button"
          aria-label="Log out"
          title="Log out"
          onClick={onLogout}
          className="p-2 text-[#8893A5] hover:text-[#B53A3A] hover:bg-[#FCEEEE] rounded-lg transition-colors"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );
};
