import React from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  FileText,
  Sparkles,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { Submission } from '../../types/docgrading';

interface StudentStatusTimelineViewProps {
  submission: Submission;
  onBack: () => void;
  onViewResult?: () => void;
}

export const StudentStatusTimelineView: React.FC<StudentStatusTimelineViewProps> = ({
  submission,
  onBack,
  onViewResult,
}) => {
  const steps = [
    {
      id: 'received',
      label: 'Đã tiếp nhận file PDF',
      desc: 'Hệ thống đã lưu trữ file và tạo checksum phiên bản.',
      done: true,
      time: '10:15:30',
    },
    {
      id: 'checking_pdf',
      label: 'Kiểm tra Text Layer & Cấu trúc',
      desc: 'Xác thực file text-native, không chứa ảnh scan.',
      done: true,
      time: '10:15:35',
    },
    {
      id: 'evaluating',
      label: 'Phân tích tự động theo 12 tiêu chí SRS',
      desc: 'Trích xuất bảng biểu, Use Case, Actor và ma trận truy vết.',
      done: ['needs_review', 'pending_approval', 'approved', 'published'].includes(
        submission.status
      ),
      time: '10:16:12',
    },
    {
      id: 'needs_review',
      label: 'Chuyển giao Giảng viên xem xét & duyệt',
      desc: 'Kết quả tự động đóng vai trò đề xuất để giảng viên đánh giá và cho điểm chính thức.',
      done: ['approved', 'published'].includes(submission.status),
      current: ['needs_review', 'pending_approval'].includes(submission.status),
      time: '10:16:20',
    },
    {
      id: 'published',
      label: 'Công bố kết quả chính thức',
      desc: 'Giảng viên đã phê duyệt và công bố bảng điểm cùng nhận xét chi tiết.',
      done: submission.status === 'published',
      time: submission.publishedAt || 'Chờ giảng viên công bố',
    },
  ];

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Quay lại danh sách bài nộp</span>
      </button>

      {/* Header card */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-md bg-sky-50 text-sky-700 font-mono text-xs font-bold border border-sky-200/80">
              {submission.courseCode}
            </span>
            <span className="text-xs text-slate-500 font-mono">{submission.fileName}</span>
          </div>
          <span className="text-xs font-medium text-slate-400">Phiên bản: v{submission.version}</span>
        </div>

        <h1 className="text-base font-bold text-slate-900 mt-2">{submission.assignmentTitle}</h1>
        <p className="text-xs text-slate-500 mt-1">
          Nộp lúc: {submission.submittedAt} • Dung lượng: {submission.fileSize} • Số trang: {submission.pageCount}
        </p>
      </div>

      {/* Timeline Card */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-2xs space-y-6">
        <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
          Tiến trình xử lý & Đánh giá bài nộp
        </h2>

        <div className="relative pl-6 space-y-8 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
          {steps.map((step, idx) => (
            <div key={step.id} className="relative flex items-start gap-4">
              <div
                className={`absolute -left-6 top-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ring-4 ring-white ${
                  step.done
                    ? 'bg-emerald-500 text-white'
                    : step.current
                    ? 'bg-sky-500 text-white animate-pulse'
                    : 'bg-slate-200 text-slate-400'
                }`}
              >
                {step.done ? <CheckCircle2 className="w-3.5 h-3.5" /> : idx + 1}
              </div>

              <div className="flex-1 text-xs">
                <div className="flex items-center justify-between">
                  <span
                    className={`font-semibold text-sm ${
                      step.done
                        ? 'text-slate-900'
                        : step.current
                        ? 'text-sky-600'
                        : 'text-slate-400'
                    }`}
                  >
                    {step.label}
                  </span>
                  <span className="text-[11px] font-mono text-slate-400">{step.time}</span>
                </div>
                <p className="text-slate-500 mt-1 leading-relaxed">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {submission.status === 'published' && onViewResult && (
          <div className="pt-4 border-t border-slate-100 flex justify-end">
            <button
              type="button"
              onClick={onViewResult}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700"
            >
              Mở trang kết quả chính thức
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
