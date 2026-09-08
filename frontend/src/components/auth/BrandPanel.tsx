import React from 'react';
import { ProductPreview } from './ProductPreview';
import { Shield, Check } from 'lucide-react';

export const BrandPanel: React.FC = () => {
  return (
    <div className="relative hidden lg:flex flex-col justify-between w-[46%] min-h-screen p-8 xl:p-12 bg-gradient-to-br from-[#122742] via-[#193B64] to-[#0E2038] text-white overflow-hidden select-none border-r border-[#193B64]/60">
      {/* Ultra-subtle engineering grid overlay (clean geometric, no wild glowing blobs) */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.035]"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, #FFFFFF 1px, transparent 0)`,
          backgroundSize: '24px 24px',
        }}
      />

      {/* Top: RPA Official Brand Identity */}
      <div className="relative z-10">
        <div className="flex items-center gap-3">
          {/* RPA Emblem */}
          <div className="w-10 h-10 rounded-xl bg-white/10 border border-white/20 flex items-center justify-center shadow-[0_2px_10px_rgba(0,0,0,0.2)]">
            <svg
              className="w-5 h-5 text-white"
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
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold tracking-tight text-white">DocGrading</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-white/10 text-white/80 font-mono font-medium tracking-wide">
                SRS RUBRIC
              </span>
            </div>
            <p className="text-[11px] text-white/60 tracking-normal font-medium">
              Hệ thống đánh giá báo cáo PDF học thuật chuẩn
            </p>
          </div>
        </div>
      </div>

      {/* Middle: Headline + Description + Realistic Product Preview */}
      <div className="relative z-10 my-auto py-6">
        <div className="max-w-[480px] mb-6 text-left">
          <h1 className="text-[26px] xl:text-[30px] font-semibold text-white tracking-tight leading-[1.3] mb-3">
            Hạ tầng xác thực &amp; kiểm soát truy cập an toàn
          </h1>
          <p className="text-sm xl:text-[15px] text-white/75 leading-relaxed font-normal">
            Bảo mật cấp doanh nghiệp với kiến trúc Zero-Trust, phân quyền đa tầng và đồng bộ danh tính theo thời gian thực.
          </p>
        </div>

        {/* Live Product Preview Component */}
        <div className="mt-6">
          <ProductPreview />
        </div>
      </div>

      {/* Bottom: Social Proof / Value Pillars */}
      <div className="relative z-10 pt-4 border-t border-white/10">
        <div className="flex items-center justify-between text-[12px] text-white/60 font-medium">
          <span className="flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5 text-emerald-400" strokeWidth={2.5} />
            <span>Quản lý tập trung</span>
          </span>
          <span className="text-white/20">•</span>
          <span className="flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5 text-emerald-400" strokeWidth={2.5} />
            <span>Dữ liệu nhất quán</span>
          </span>
          <span className="text-white/20">•</span>
          <span className="flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5 text-emerald-400" strokeWidth={2.5} />
            <span>Theo dõi thời gian thực</span>
          </span>
        </div>
      </div>
    </div>
  );
};
