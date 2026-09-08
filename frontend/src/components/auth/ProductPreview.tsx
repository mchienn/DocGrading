import React from 'react';
import {
  ShieldCheck,
  Server,
  Activity,
  CheckCircle2,
  Lock,
  Clock,
  ArrowUpRight,
  Database,
  Layers,
} from 'lucide-react';

export const ProductPreview: React.FC = () => {
  return (
    <div className="w-full max-w-[480px] rounded-2xl border border-white/10 bg-[#0F243E]/80 backdrop-blur-md p-5 text-white shadow-[0_20px_50px_rgba(0,0,0,0.35)] overflow-hidden">
      {/* Top Header of the SaaS Console */}
      <div className="flex items-center justify-between pb-3.5 border-b border-white/10 text-xs">
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 relative">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="font-semibold text-white/90 tracking-tight">RPA Control Plane</span>
          <span className="text-white/40">•</span>
          <span className="text-white/60 text-[11px] font-mono">Cluster VN-North-01</span>
        </div>
        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-[11px] font-medium">
          <ShieldCheck className="w-3 h-3" />
          <span>Bảo mật cấp 4</span>
        </div>
      </div>

      {/* Real-time Metric Cards Grid */}
      <div className="grid grid-cols-3 gap-2.5 my-3.5">
        <div className="bg-white/[0.04] border border-white/10 rounded-xl p-2.5 text-left">
          <div className="flex items-center justify-between text-white/50 text-[11px] mb-1">
            <span>Phiên an toàn</span>
            <ArrowUpRight className="w-3 h-3 text-emerald-400" />
          </div>
          <div className="text-lg font-semibold tracking-tight text-white">18,420</div>
          <div className="text-[10px] text-emerald-400 font-medium mt-0.5">+12.4% hôm nay</div>
        </div>

        <div className="bg-white/[0.04] border border-white/10 rounded-xl p-2.5 text-left">
          <div className="flex items-center justify-between text-white/50 text-[11px] mb-1">
            <span>Uptime SLA</span>
            <Activity className="w-3 h-3 text-sky-400" />
          </div>
          <div className="text-lg font-semibold tracking-tight text-white">99.98%</div>
          <div className="text-[10px] text-white/50 font-medium mt-0.5">30 ngày qua</div>
        </div>

        <div className="bg-white/[0.04] border border-white/10 rounded-xl p-2.5 text-left">
          <div className="flex items-center justify-between text-white/50 text-[11px] mb-1">
            <span>Xác thực 2FA</span>
            <Lock className="w-3 h-3 text-amber-400" />
          </div>
          <div className="text-lg font-semibold tracking-tight text-white">100%</div>
          <div className="text-[10px] text-white/50 font-medium mt-0.5">RBAC bắt buộc</div>
        </div>
      </div>

      {/* Live Security & Access Stream snippet */}
      <div className="bg-white/[0.02] border border-white/10 rounded-xl p-3 text-left">
        <div className="flex items-center justify-between mb-2 text-[11px]">
          <span className="font-medium text-white/70 uppercase tracking-wider text-[10px]">
            Nhật ký kiểm soát truy cập thời gian thực
          </span>
          <span className="flex items-center gap-1 text-white/40 text-[10px]">
            <Clock className="w-2.5 h-2.5" />
            <span>Đồng bộ tức thì</span>
          </span>
        </div>

        <div className="space-y-2 text-xs">
          <div className="flex items-center justify-between py-1 border-b border-white/[0.06]">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
              <div className="truncate">
                <span className="text-white/90 font-medium">SSO Enterprise SAML 2.0</span>
                <span className="text-white/40 ml-1.5 text-[11px]">user.lead@domain.vn</span>
              </div>
            </div>
            <span className="text-[11px] font-mono text-emerald-300/90 ml-2 flex-shrink-0">
              Đã xác thực
            </span>
          </div>

          <div className="flex items-center justify-between py-1 border-b border-white/[0.06]">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-1.5 h-1.5 rounded-full bg-sky-400 flex-shrink-0" />
              <div className="truncate">
                <span className="text-white/90 font-medium">Chính sách RBAC v2.4</span>
                <span className="text-white/40 ml-1.5 text-[11px]">Scope: Evaluation_Admin</span>
              </div>
            </div>
            <span className="text-[11px] font-mono text-sky-300/90 ml-2 flex-shrink-0">
              Thực thi
            </span>
          </div>

          <div className="flex items-center justify-between py-1">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-1.5 h-1.5 rounded-full bg-purple-400 flex-shrink-0" />
              <div className="truncate">
                <span className="text-white/90 font-medium">Khóa phiên TLS 1.3 / mTLS</span>
                <span className="text-white/40 ml-1.5 text-[11px]">Gateway Hanoi Edge-02</span>
              </div>
            </div>
            <span className="text-[11px] font-mono text-purple-300/90 ml-2 flex-shrink-0">
              Khởi tạo
            </span>
          </div>
        </div>
      </div>

      {/* Cluster Nodes Mini Status Footer */}
      <div className="mt-3 pt-2.5 border-t border-white/10 flex items-center justify-between text-[11px] text-white/50">
        <div className="flex items-center gap-2">
          <Server className="w-3.5 h-3.5 text-white/40" />
          <span>4/4 Nodes khả dụng</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5 text-white/40" />
          <span>Multi-region Sync</span>
        </div>
        <div className="flex items-center gap-1">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-emerald-300 font-medium">Zero-Trust</span>
        </div>
      </div>
    </div>
  );
};
