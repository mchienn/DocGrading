import React from 'react';
import { UserSession } from '../types/auth';
import {
  ShieldCheck,
  LogOut,
  Building,
  Mail,
  Phone,
  Clock,
  ArrowRight,
  ExternalLink,
  Layers,
} from 'lucide-react';

interface WorkspaceSuccessPageProps {
  user: UserSession;
  onLogout: () => void;
  onNavigate: (screen: string) => void;
  onEnterWorkspace?: () => void;
}

export const WorkspaceSuccessPage: React.FC<WorkspaceSuccessPageProps> = ({
  user,
  onLogout,
  onNavigate,
  onEnterWorkspace,
}) => {
  return (
    <div className="w-full max-w-[500px] mx-auto bg-white rounded-2xl border border-[#D9E0E8] p-6 sm:p-8 shadow-[0_4px_24px_rgba(0,0,0,0.06)] text-left animate-in fade-in duration-200">
      <div className="flex items-center justify-between pb-4 border-b border-[#D9E0E8]">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-[#193B64] text-white flex items-center justify-center font-bold text-base shadow-sm">
            {user.fullName.charAt(0)}
          </div>
          <div>
            <h2 className="text-[17px] font-semibold text-[#172033] leading-tight">
              {user.fullName}
            </h2>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[12px] text-[#667085]">{user.email}</span>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.2 bg-[#F0F9F5] border border-[#CEEADB] text-[#178557] rounded-full text-[10px] font-medium">
                <ShieldCheck className="w-3 h-3" /> Đã xác thực
              </span>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={onLogout}
          className="text-[#667085] hover:text-[#C9362B] p-2 rounded-lg hover:bg-[#FDF3F2] transition-colors"
          title="Đăng xuất"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>

      <div className="my-5 space-y-3 text-[13px]">
        <div className="p-3.5 rounded-xl bg-[#F5F7FA] border border-[#D9E0E8]/70 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-[#667085] flex items-center gap-2">
              <Building className="w-4 h-4 text-[#193B64]" />
              Đơn vị:
            </span>
            <span className="font-semibold text-[#172033]">
              {user.department || user.organization || 'Trường Đại học'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#667085] flex items-center gap-2">
              <Layers className="w-4 h-4 text-[#193B64]" />
              Vai trò (Role):
            </span>
            <span className="font-semibold text-[#193B64] uppercase text-[11px] px-2.5 py-0.5 bg-[#EFF5FC] rounded-md border border-[#D4E4F5]">
              {user.role === 'teacher'
                ? 'Giảng viên (Teacher)'
                : user.role === 'admin'
                ? 'Quản trị viên (Admin)'
                : 'Sinh viên (Student)'}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#667085] flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#193B64]" />
              Phiên bảo mật:
            </span>
            <span className="font-mono text-[11px] text-[#178557] font-medium">
              TLS 1.3 Active (Zero-Trust)
            </span>
          </div>
        </div>

        <div className="p-3.5 rounded-xl bg-[#EFF5FC] border border-[#D4E4F5] text-[12px] text-[#193B64] leading-relaxed">
          <strong>Thông báo phân quyền:</strong> Bạn đã xác thực danh tính thành công. Các chức năng và quyền truy xuất dữ liệu trong hệ thống DocGrading sẽ tương ứng với vai trò được cấp phép.
        </div>
      </div>

      <div className="space-y-2.5 pt-2">
        {onEnterWorkspace && (
          <button
            type="button"
            onClick={onEnterWorkspace}
            className="w-full h-12 rounded-xl bg-[#193B64] hover:bg-[#102A49] text-white text-[14px] font-medium flex items-center justify-center gap-2 transition-colors shadow-sm"
          >
            <span>Vào Không gian làm việc DocGrading</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        )}

        <button
          type="button"
          onClick={() => onNavigate('login')}
          className="w-full h-11 rounded-xl border border-[#D9E0E8] bg-white hover:bg-[#F9FAFC] text-[#172033] text-[13px] font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <span>Khám phá các màn hình Auth khác</span>
        </button>

        <button
          type="button"
          onClick={() => onLogout()}
          className="w-full h-10 text-[#667085] hover:text-[#C9362B] text-[12px] font-medium flex items-center justify-center gap-1.5 transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span>Đăng xuất tài khoản</span>
        </button>
      </div>
    </div>
  );
};
