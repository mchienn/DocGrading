import React from 'react';
import { AuthFooter } from './AuthFooter';

interface AuthShellProps {
  children: React.ReactNode;
  activeScreen?: string;
  onScreenChange?: (screen: string) => void;
}

export const AuthShell: React.FC<AuthShellProps> = ({ children }) => {
  return (
    <div className="min-h-screen w-full bg-[#F5F7FA] text-[#172033] flex flex-col justify-between antialiased">
      {/* Main Centered Authentication Area */}
      <main className="flex-1 flex flex-col justify-center items-center p-4 sm:p-8 lg:p-12 w-full">
        <div className="w-full flex items-center justify-center my-auto py-6 sm:py-10">
          {children}
        </div>
      </main>

      {/* Production Footer */}
      <AuthFooter />
    </div>
  );
};
