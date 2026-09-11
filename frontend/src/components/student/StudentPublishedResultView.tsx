import React from 'react';
import {
  ArrowLeft,
  Award,
  CheckCircle2,
  FileText,
  AlertCircle,
  HelpCircle,
  MessageSquare,
  GitCompare,
  Download,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react';
import { Submission } from '../../types/docgrading';

interface StudentPublishedResultViewProps {
  submission: Submission;
  onBack: () => void;
  onOpenAppeal: (submission: Submission) => void;
  onOpenCompare: (submission: Submission) => void;
}

export const StudentPublishedResultView: React.FC<StudentPublishedResultViewProps> = ({
  submission,
  onBack,
  onOpenAppeal,
  onOpenCompare,
}) => {

  const finalScore100 = submission.finalScore ?? submission.proposedScore;
  const finalScore10 = (finalScore100 / 10).toFixed(1);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Top action / back */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Quay lại danh sách đợt nộp</span>
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onOpenCompare(submission)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-700 bg-white hover:bg-slate-50 text-xs font-medium"
          >
            <GitCompare className="w-3.5 h-3.5 text-slate-500" />
            <span>So sánh phiên bản</span>
          </button>
          <button
            type="button"
            onClick={() => onOpenAppeal(submission)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-800 text-xs font-medium"
          >
            <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
            <span>Gửi yêu cầu phúc khảo</span>
          </button>
        </div>
      </div>

      {/* Official Score Hero Banner */}
      <div className="bg-slate-900 text-white rounded-2xl p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-semibold">
              Kết quả chính thức đã công bố
            </span>
            <span className="text-xs text-slate-400 font-mono">Phiên bản v{submission.version}</span>
          </div>
          <h1 className="text-xl font-bold text-white">{submission.assignmentTitle}</h1>
          <p className="text-xs text-slate-300">
            Giảng viên duyệt: <strong>{submission.reviewerName || 'TS. Lê Hoàng Nam'}</strong> • Công bố:{' '}
            {submission.publishedAt || '02/09/2026 14:30'}
          </p>
        </div>

        <div className="flex items-center gap-6 bg-slate-800/80 p-4 rounded-xl border border-slate-700/80 shrink-0">
          <div>
            <span className="text-[10px] uppercase tracking-wider text-slate-400 block font-medium">
              Thang 100
            </span>
            <span className="text-3xl font-black font-mono text-white tracking-tight">
              {finalScore100.toFixed(1)}
            </span>
            <span className="text-xs text-slate-400">/100</span>
          </div>
          <div className="w-px h-10 bg-slate-700"></div>
          <div>
            <span className="text-[10px] uppercase tracking-wider text-emerald-400 block font-medium">
              Thang 10
            </span>
            <span className="text-3xl font-black font-mono text-emerald-400 tracking-tight">
              {finalScore10}
            </span>
            <span className="text-xs text-emerald-300">/10.0</span>
          </div>
        </div>
      </div>

      {/* Criteria Breakdown List */}
      <div className="space-y-3">
        <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
          Bảng điểm chi tiết theo 12 tiêu chí Rubric IEEE 830
        </h2>

        <div className="space-y-3">
          {submission.criteriaResults.map((res) => {
            const scorePercent = ((res.confirmedLevel / 4) * res.weight).toFixed(1);
            const publishedFindings = res.findings.filter((finding) => finding.status !== 'rejected');
            return (
              <div
                key={res.criterionId}
                className="bg-white rounded-xl border border-slate-200 p-4 shadow-2xs space-y-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-bold text-xs text-slate-900">{res.criterionName}</h3>
                    <span className="text-[11px] text-slate-500">Trọng số: {res.weight}%</span>
                  </div>

                  <div className="text-right">
                    <span className="text-xs font-bold font-mono text-slate-900">
                      Mức {res.confirmedLevel}/4
                    </span>
                    <div className="text-[11px] font-mono text-emerald-700 font-semibold">
                      +{scorePercent}%
                    </div>
                  </div>
                </div>

                {/* Teacher comments if any */}
                {res.teacherNotes && (
                  <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100 text-xs text-slate-700 whitespace-pre-line">
                    <strong className="text-slate-900 block mb-0.5">Nhận xét của giảng viên:</strong>
                    {res.teacherNotes}
                  </div>
                )}

                {/* Published findings & evidence */}
                {publishedFindings.length > 0 && (
                  <div className="space-y-2 pt-1 border-t border-slate-100 text-xs">
                    {publishedFindings.map((f) => (
                      <div
                        key={f.id}
                        className="p-3 bg-slate-50 rounded-lg border border-slate-200 space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-slate-900">{f.title}</span>
                          <span className="text-[10px] font-mono bg-white px-2 py-0.5 rounded border border-slate-200 text-slate-600">
                            Trang {f.pageNumber} — {f.section}
                          </span>
                        </div>
                        <p className="text-slate-600 leading-relaxed text-[11px]">{f.description}</p>
                        <div className="p-2 bg-white rounded border border-slate-200/80 text-[11px] text-sky-800">
                          <span className="font-semibold">Chỉ dẫn khắc phục:</span> {f.suggestion}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
