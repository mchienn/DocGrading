import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { WorkspaceRole } from '../../types/api';

interface AppHeaderProps {
  activeRole: WorkspaceRole;
  title: string;
}

const roleLabels: Record<WorkspaceRole, string> = {
  teacher: 'Teacher',
  student: 'Student',
  admin: 'Admin',
};

export const AppHeader: React.FC<AppHeaderProps> = ({ activeRole, title }) => (
  <header className="h-14 bg-white border-b border-[#DDE2E8] px-6 flex items-center sticky top-0 z-20">
    <div className="flex items-center gap-2 text-xs">
      <span className="text-[#8893A5]">{roleLabels[activeRole]}</span>
      <ChevronRight className="w-3.5 h-3.5 text-[#CBD5E1]" />
      <span className="text-[#172033] font-semibold">{title}</span>
    </div>
  </header>
);
