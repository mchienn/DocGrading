import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { User, Bell, FileText, Settings } from 'lucide-react';
import type { WorkspaceRole } from '../../types/api';

interface AccountNavProps {
  activeRole: WorkspaceRole;
}

export const AccountNav: React.FC<AccountNavProps> = ({ activeRole }) => {
  const location = useLocation();

  const tabs = [
    { path: `/${activeRole}/profile`, label: 'Profile', icon: User },
    { path: `/${activeRole}/notifications`, label: 'Notifications', icon: Bell },
    { path: `/${activeRole}/files`, label: 'Files', icon: FileText },
    { path: `/${activeRole}/settings`, label: 'Settings', icon: Settings },
  ];

  return (
    <nav aria-label="Account navigation" className="flex border-b border-[#DDE2E8] bg-white px-4 sm:px-8 gap-1 sm:gap-6 overflow-x-auto shrink-0">
      {tabs.map(({ path, label, icon: Icon }) => {
        const active = location.pathname === path;
        return (
          <Link
            key={path}
            to={path}
            aria-current={active ? 'page' : undefined}
            className={`inline-flex items-center gap-2 py-3 px-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              active
                ? 'border-[#1F4B7A] text-[#1F4B7A] font-semibold'
                : 'border-transparent text-[#596579] hover:text-[#172033] hover:border-slate-300'
            }`}
          >
            <Icon className="w-4 h-4" />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
};
