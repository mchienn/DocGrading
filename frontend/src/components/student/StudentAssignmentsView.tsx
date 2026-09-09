import React from 'react';
import {
  FolderKanban,
  Calendar,
  FileText,
  UploadCloud,
  CheckCircle2,
  Clock,
  ArrowRight,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { Assignment, Submission } from '../../types/docgrading';

interface StudentAssignmentsViewProps {
  assignments: Assignment[];
  mySubmissions: Submission[];
  onOpenUpload: (assignment: Assignment) => void;
  onOpenResult: (submission: Submission) => void;
  onOpenStatus: (submission: Submission) => void;
}

export const StudentAssignmentsView: React.FC<StudentAssignmentsViewProps> = ({
  assignments,
  mySubmissions,
  onOpenUpload,
  onOpenResult,
  onOpenStatus,
}) => {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900">Các đợt nộp Báo cáo học thuật</h1>
        <p className="text-xs text-slate-500 mt-1">
          Theo dõi hạn chót nộp tài liệu SRS, kết quả đánh giá đã công bố và các nhận xét từ giảng viên.
        </p>
      </div>

      {/* Grid of assignments */}
      <div className="space-y-4">
        {assignments.map((assignment) => {
          const submission = mySubmissions.find((s) => s.assignmentId === assignment.id);
          const isPublished = submission?.status === 'published';
          const isProcessing =
            submission &&
            ['received', 'checking_pdf', 'queued', 'evaluating', 'needs_review', 'pending_approval', 'approved'].includes(
              submission.status
            );
          const isError = submission?.status === 'error';

          return (
            <div
              key={assignment.id}
              className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs hover:border-slate-300 transition-all flex flex-col md:flex-row md:items-center justify-between gap-5"
            >
              <div className="space-y-2 max-w-2xl">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded-md bg-sky-50 text-sky-700 font-mono text-[11px] font-bold border border-sky-200/80">
                    {assignment.courseCode}
                  </span>
                  <span className="text-xs text-slate-500">{assignment.courseName}</span>
                </div>

                <h3 className="text-base font-bold text-slate-900">{assignment.title}</h3>
                <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed">
                  {assignment.description}
                </p>

                <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 pt-1">
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    Hạn chót:{' '}
                    <strong className="text-slate-700 font-medium">
                      {new Date(assignment.dueDate).toLocaleDateString('vi-VN')}
                    </strong>
                  </span>
                  <span>•</span>
                  <span>Định dạng: PDF text-native (Tối đa {assignment.requirements.maxFileSizeMb}MB)</span>
                  <span>•</span>
                  <span>Số lần nộp tối đa: {assignment.maxSubmissions} lần</span>
                </div>
              </div>

              {/* Status and CTA action */}
              <div className="flex flex-col sm:flex-row md:flex-col lg:flex-row items-start sm:items-center md:items-end lg:items-center gap-3 shrink-0 pt-3 md:pt-0 border-t md:border-t-0 border-slate-100">
                {/* Status Indicator */}
                {submission ? (
                  isPublished ? (
                    <div className="text-right">
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Đã có kết quả chính thức</span>
                      </span>
                      <p className="text-xs font-mono font-bold text-slate-900 mt-1">
                        Điểm: {(submission.finalScore ?? submission.proposedScore).toFixed(1)}/100
                      </p>
                    </div>
                  ) : isError ? (
                    <div className="text-right">
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700 bg-rose-50 px-2.5 py-1 rounded-md border border-rose-200">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>Lỗi định dạng PDF</span>
                      </span>
                      <p className="text-[11px] text-slate-400 mt-0.5">Yêu cầu nộp lại bản text-layer</p>
                    </div>
                  ) : (
                    <div className="text-right">
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-sky-700 bg-sky-50 px-2.5 py-1 rounded-md border border-sky-200">
                        <Clock className="w-3.5 h-3.5" />
                        <span>Đang xử lý & Chờ duyệt</span>
                      </span>
                      <p className="text-[11px] text-slate-400 mt-0.5">Đã nộp v{submission.version}</p>
                    </div>
                  )
                ) : (
                  <span className="text-xs text-amber-700 bg-amber-50 px-2.5 py-1 rounded-md border border-amber-200 font-medium">
                    Chưa nộp bài
                  </span>
                )}

                {/* Primary CTA */}
                {submission && isPublished ? (
                  <button
                    type="button"
                    onClick={() => onOpenResult(submission)}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors shadow-2xs"
                  >
                    <span>Xem kết quả & Bằng chứng</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                ) : submission && isProcessing ? (
                  <button
                    type="button"
                    onClick={() => onOpenStatus(submission)}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition-colors shadow-2xs"
                  >
                    <span>Xem tiến độ xử lý</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onOpenUpload(assignment)}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors shadow-2xs"
                  >
                    <UploadCloud className="w-4 h-4 text-sky-400" />
                    <span>Nộp bài PDF ngay</span>
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
