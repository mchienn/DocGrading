import React from 'react';
import { ArrowLeft, ShieldCheck } from 'lucide-react';

interface AuthFormCardProps {
  children: React.ReactNode;
  backTo?: {
    label: string;
    onClick: () => void;
  };
  showSecurityBadge?: boolean;
}

export const AuthFormCard: React.FC<AuthFormCardProps> = ({
  children,
  backTo,
  showSecurityBadge = true,
}) => {
  return (
    <div className="w-full max-w-[440px] mx-auto">
      {/* Branding Bar with Security Protocol */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[#193B64] flex items-center justify-center text-white shadow-xs">
            <svg
              className="w-4 h-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polygon points="12 2 2 7 12 12 22 7 12 2" />
              <polyline points="2 17 12 22 22 17" />
              <polyline points="2 12 12 17 22 12" />
            </svg>
          </div>
          <div>
            <span className="text-base font-bold tracking-tight text-[#172033]">DocGrading</span>
            <span className="text-[11px] text-[#667085] ml-1.5 font-medium">SRS Edition</span>
          </div>
        </div>

        <div className="text-[11px] px-2 py-0.5 rounded-full bg-[#178557]/10 text-[#178557] font-medium border border-[#178557]/20">
          TLS 1.3
        </div>
      </div>

      {/* Top back/breadcrumb button if available */}
      {backTo && (
        <div className="mb-4">
          <button
            type="button"
            onClick={backTo.onClick}
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-[#667085] hover:text-[#172033] transition-colors focus:outline-none"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>{backTo.label}</span>
          </button>
        </div>
      )}

      {/* Surface Card */}
      <div className="bg-white rounded-2xl border border-[#D9E0E8] p-6 sm:p-8 shadow-[0_1px_3px_rgba(0,0,0,0.03),0_8px_24px_rgba(0,0,0,0.04)] text-left">
        {children}
      </div>

      {/* Security microcopy line below card */}
      {showSecurityBadge && (
        <div className="mt-4 flex items-center justify-center gap-1.5 text-[11px] text-[#667085]">
          <ShieldCheck className="w-3.5 h-3.5 text-[#178557] flex-shrink-0" />
          <span>Phiên kết nối của bạn được bảo vệ bằng mã hóa TLS 1.3 theo tiêu chuẩn ISO 27001.</span>
        </div>
      )}
    </div>
  );
};
