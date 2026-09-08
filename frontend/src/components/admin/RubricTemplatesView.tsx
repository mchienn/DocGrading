import React from 'react';
import { Settings2, ShieldCheck, Layers, Copy, CheckCircle2 } from 'lucide-react';
import { DEFAULT_SRS_CRITERIA } from '../../data/mockData';

export const RubricTemplatesView: React.FC = () => {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Mẫu Rubric Đánh giá Mặc định (Templates)</h1>
          <p className="text-xs text-slate-500 mt-1">
            Quản lý các bộ tiêu chí rubric chuẩn cho báo cáo SRS IEEE 830, kiến trúc hệ thống và đồ án tốt nghiệp.
          </p>
        </div>

        <button
          type="button"
          className="px-3.5 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800"
        >
          Tạo bộ Rubric mới
        </button>
      </div>

      {/* Active Rubric Card */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-sky-50 text-sky-700 flex items-center justify-center font-bold">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">Rubric SRS Chuẩn IEEE 830 (v1.0 Baseline)</h2>
              <p className="text-xs text-slate-500">Mã: RUBRIC-SRS-DEFAULT • Trạng thái: Đang kích hoạt (Active)</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-semibold font-mono">
              Tổng trọng số: 100%
            </span>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border border-slate-200 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Copy className="w-3.5 h-3.5" />
              <span>Nhân bản</span>
            </button>
          </div>
        </div>

        <div className="border-t border-slate-100 pt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {DEFAULT_SRS_CRITERIA.map((c) => (
              <div
                key={c.id}
                className="p-3 bg-slate-50 rounded-lg border border-slate-200/80 flex items-start justify-between gap-3"
              >
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono font-bold text-slate-800">{c.code}</span>
                    <span className="font-semibold text-slate-900">{c.name}</span>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">{c.description}</p>
                </div>
                <div className="text-right shrink-0">
                  <span className="font-bold text-slate-900 font-mono text-sm">{c.weight}%</span>
                  <div className="text-[10px] text-slate-400 font-mono mt-0.5">{c.defaultEvaluator}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
