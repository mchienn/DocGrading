import React from 'react';
import { ArrowLeft, GitCompare, CheckCircle2, TrendingUp, AlertTriangle } from 'lucide-react';
import { Submission } from '../../types/docgrading';

interface VersionCompareViewProps {
  currentSubmission: Submission;
  onBack: () => void;
}

export const VersionCompareView: React.FC<VersionCompareViewProps> = ({
  currentSubmission,
  onBack,
}) => {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Quay lại kết quả</span>
      </button>

      {/* Header */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs">
        <div className="flex items-center gap-2 text-xs font-medium text-sky-700 bg-sky-50 px-2.5 py-1 rounded-md w-fit border border-sky-200">
          <GitCompare className="w-3.5 h-3.5" />
          <span>So sánh lịch sử cải thiện giữa 2 lần nộp</span>
        </div>
        <h1 className="text-lg font-bold text-slate-900 mt-2">
          So sánh Phiên bản v1.0 vs v{currentSubmission.version}.0
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Hệ thống đối chiếu điểm số, các tiêu chí đã khắc phục và các vấn đề còn tồn đọng.
        </p>
      </div>

      {/* Score Comparison Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-1">
          <span className="text-slate-400 block font-medium">Phiên bản trước (v1.0)</span>
          <p className="text-2xl font-bold font-mono text-slate-700">76.0 / 100</p>
          <span className="text-[11px] text-slate-400">Nộp ngày 28/08/2026</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-1">
          <span className="text-slate-400 block font-medium">
            Phiên bản hiện tại (v{currentSubmission.version}.0)
          </span>
          <p className="text-2xl font-bold font-mono text-emerald-600">
            {(currentSubmission.finalScore ?? currentSubmission.proposedScore).toFixed(1)} / 100
          </p>
          <span className="text-[11px] text-slate-400">Nộp ngày 05/09/2026</span>
        </div>

        <div className="bg-emerald-50/80 p-4 rounded-xl border border-emerald-200 text-emerald-900 space-y-1">
          <div className="flex items-center gap-1.5 font-bold">
            <TrendingUp className="w-4 h-4 text-emerald-600" />
            <span>Mức cải thiện điểm</span>
          </div>
          <p className="text-2xl font-bold font-mono text-emerald-700">+8.0 điểm (+10.5%)</p>
          <span className="text-[11px] text-emerald-600">Đã giải quyết 3 lỗi cấu trúc chính</span>
        </div>
      </div>

      {/* Details Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden text-xs">
        <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 font-bold text-slate-800">
          Đối chiếu theo tiêu chí quan trọng
        </div>
        <div className="divide-y divide-slate-100 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold text-slate-900">SRS-01: Cấu trúc & Mục lục chuẩn IEEE 830</p>
              <p className="text-[11px] text-slate-500">Đã bổ sung đầy đủ Mục 3.2 theo chuẩn IEEE</p>
            </div>
            <span className="px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 font-mono font-bold">
              Mức 2 → Mức 4 (+4.0%)
            </span>
          </div>

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-slate-900">SRS-06: Khả năng kiểm thử (Testability)</p>
              <p className="text-[11px] text-slate-500">Đã định lượng chỉ số thời gian xử lý đơn hàng</p>
            </div>
            <span className="px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 font-mono font-bold">
              Mức 2 → Mức 3 (+3.0%)
            </span>
          </div>

          <div className="flex items-center justify-between pt-3">
            <div>
              <p className="font-semibold text-slate-900">SRS-09: Ma trận truy vết (Traceability Matrix)</p>
              <p className="text-[11px] text-amber-600">Vẫn còn thiếu ánh xạ UC-08 sang FR-019</p>
            </div>
            <span className="px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 font-mono font-bold">
              Giữ nguyên Mức 3
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
