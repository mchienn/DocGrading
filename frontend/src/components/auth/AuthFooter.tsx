import React from 'react';

export const AuthFooter: React.FC = () => {
  return (
    <footer className="w-full pt-6 pb-2 mt-auto text-center">
      <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[12px] text-[#667085]">
        <a
          href="#terms"
          onClick={(e) => e.preventDefault()}
          className="hover:text-[#172033] transition-colors"
        >
          Điều khoản dịch vụ
        </a>
        <span className="text-[#D9E0E8] select-none">•</span>
        <a
          href="#privacy"
          onClick={(e) => e.preventDefault()}
          className="hover:text-[#172033] transition-colors"
        >
          Chính sách bảo mật
        </a>
        <span className="text-[#D9E0E8] select-none">•</span>
        <a
          href="#help"
          onClick={(e) => e.preventDefault()}
          className="hover:text-[#172033] transition-colors"
        >
          Trung tâm trợ giúp
        </a>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3 mt-3 text-[11px] text-[#667085]/80">
        <span>© 2026 RPA Platform. Bản quyền thuộc RPA.</span>
        <span className="text-[#D9E0E8] hidden sm:inline select-none">•</span>
        <span className="inline-flex items-center gap-1.5 font-medium text-[#178557]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#178557] inline-block animate-pulse" />
          Hệ thống hoạt động bình thường
        </span>
      </div>
    </footer>
  );
};
