import React, { useState } from 'react';
import {
  Search,
  Filter,
  FileCheck2,
  AlertCircle,
  CheckCircle2,
  Clock,
  Sparkles,
  Send,
  Eye,
  FileText,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react';
import { Submission, SubmissionStatus, Assignment } from '../../types/docgrading';

interface SubmissionQueueViewProps {
  submissions: Submission[];
  assignments: Assignment[];
  selectedAssignmentId?: string;
  onSelectAssignmentFilter: (id: string) => void;
  onOpenReview: (submission: Submission) => void;
  onBatchPublish: () => void;
}

export const SubmissionQueueView: React.FC<SubmissionQueueViewProps> = ({
  submissions,
  assignments,
  selectedAssignmentId,
  onSelectAssignmentFilter,
  onOpenReview,
  onBatchPublish,
}) => {
  const [filterTab, setFilterTab] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [showBatchModal, setShowBatchModal] = useState(false);

  // Filter submissions
  const filtered = submissions.filter((sub) => {
    if (selectedAssignmentId && sub.assignmentId !== selectedAssignmentId) {
      return false;
    }
    if (filterTab !== 'all') {
      if (filterTab === 'needs_review' && sub.status !== 'needs_review') return false;
      if (filterTab === 'pending_approval' && sub.status !== 'pending_approval') return false;
      if (filterTab === 'approved' && sub.status !== 'approved') return false;
      if (filterTab === 'published' && sub.status !== 'published') return false;
      if (filterTab === 'error' && sub.status !== 'error') return false;
    }
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      return (
        sub.studentName.toLowerCase().includes(term) ||
        sub.studentCode.toLowerCase().includes(term) ||
        sub.fileName.toLowerCase().includes(term)
      );
    }
    return true;
  });

  const readyToPublishCount = submissions.filter((s) => s.status === 'approved').length;

  const getStatusBadge = (status: SubmissionStatus) => {
    switch (status) {
      case 'needs_review':
        return {
          label: 'Cần xem xét',
          color: 'bg-amber-50 text-amber-700 border-amber-200',
          icon: Clock,
        };
      case 'pending_approval':
        return {
          label: 'Chờ duyệt',
          color: 'bg-sky-50 text-sky-700 border-sky-200',
          icon: Sparkles,
        };
      case 'approved':
        return {
          label: 'Đã duyệt (Chờ công bố)',
          color: 'bg-indigo-50 text-indigo-700 border-indigo-200',
          icon: CheckCircle2,
        };
      case 'published':
        return {
          label: 'Đã công bố',
          color: 'bg-emerald-50 text-emerald-700 border-emerald-200',
          icon: ShieldCheck,
        };
      case 'error':
        return {
          label: 'Lỗi PDF Scan',
          color: 'bg-rose-50 text-rose-700 border-rose-200',
          icon: AlertCircle,
        };
      default:
        return {
          label: 'Đang xử lý',
          color: 'bg-slate-100 text-slate-700 border-slate-200',
          icon: Clock,
        };
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Hàng đợi duyệt bài nộp (Submission Queue)</h1>
          <p className="text-xs text-slate-500 mt-1">
            Đánh giá các đề xuất từ Rule & AI, đối chiếu bằng chứng PDF và phê duyệt kết quả chính thức.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowBatchModal(true)}
            disabled={readyToPublishCount === 0}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-700 disabled:opacity-40 transition-colors shadow-2xs"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Công bố hàng loạt ({readyToPublishCount})</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Tìm theo tên SV, MSSV hoặc tên file..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-xs focus:outline-hidden focus:ring-1 focus:ring-sky-500"
          />
        </div>

        {/* Assignment selector dropdown */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500 font-medium shrink-0">Đợt nộp:</span>
          <select
            value={selectedAssignmentId || ''}
            onChange={(e) => onSelectAssignmentFilter(e.target.value)}
            className="px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white text-slate-800 focus:outline-hidden focus:ring-1 focus:ring-sky-500"
          >
            <option value="">Tất cả đợt nộp</option>
            {assignments.map((a) => (
              <option key={a.id} value={a.id}>
                {a.courseCode} — {a.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 border-b border-slate-200 text-xs">
        {[
          { id: 'all', label: 'Tất cả bài nộp', count: submissions.length },
          {
            id: 'needs_review',
            label: 'Cần xem xét',
            count: submissions.filter((s) => s.status === 'needs_review').length,
            color: 'text-amber-600',
          },
          {
            id: 'pending_approval',
            label: 'Chờ duyệt',
            count: submissions.filter((s) => s.status === 'pending_approval').length,
          },
          {
            id: 'approved',
            label: 'Đã duyệt',
            count: submissions.filter((s) => s.status === 'approved').length,
          },
          {
            id: 'published',
            label: 'Đã công bố',
            count: submissions.filter((s) => s.status === 'published').length,
          },
          {
            id: 'error',
            label: 'Lỗi định dạng',
            count: submissions.filter((s) => s.status === 'error').length,
            color: 'text-rose-600',
          },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setFilterTab(tab.id)}
            className={`px-3 py-2 rounded-t-lg font-medium transition-colors border-b-2 whitespace-nowrap flex items-center gap-1.5 ${
              filterTab === tab.id
                ? 'border-slate-900 text-slate-900 bg-white'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            <span>{tab.label}</span>
            <span
              className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-slate-100 ${
                tab.color || 'text-slate-600'
              }`}
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Submissions Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50/80 border-b border-slate-200 text-slate-500 font-medium">
              <tr>
                <th className="px-4 py-3">Sinh viên & MSSV</th>
                <th className="px-4 py-3">Tài liệu nộp</th>
                <th className="px-4 py-3">Thời gian</th>
                <th className="px-4 py-3 text-center">Điểm đề xuất</th>
                <th className="px-4 py-3 text-center">Độ tin cậy</th>
                <th className="px-4 py-3">Trạng thái</th>
                <th className="px-4 py-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-400">
                    Không có bài nộp nào phù hợp với bộ lọc hiện tại.
                  </td>
                </tr>
              ) : (
                filtered.map((sub) => {
                  const badge = getStatusBadge(sub.status);
                  const Icon = badge.icon;
                  return (
                    <tr key={sub.id} className="hover:bg-slate-50/60 transition-colors">
                      <td className="px-4 py-3.5">
                        <div className="font-semibold text-slate-900">{sub.studentName}</div>
                        <div className="text-[11px] text-slate-400 font-mono">MSSV: {sub.studentCode}</div>
                      </td>

                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-1.5 font-medium text-slate-800">
                          <FileText className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                          <span className="truncate max-w-xs">{sub.fileName}</span>
                        </div>
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          v{sub.version} • {sub.pageCount} trang • {sub.fileSize}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-slate-500">
                        <div>{sub.submittedAt}</div>
                        <span className="text-[10px] text-slate-400">{sub.courseCode}</span>
                      </td>

                      <td className="px-4 py-3.5 text-center">
                        {sub.status === 'error' ? (
                          <span className="text-rose-500 font-mono text-[11px]">—</span>
                        ) : (
                          <div>
                            <span className="font-bold text-sm text-slate-900 font-mono">
                              {sub.finalScore ? sub.finalScore.toFixed(1) : sub.proposedScore.toFixed(1)}
                            </span>
                            <span className="text-[10px] text-slate-400">/100</span>
                            <div className="text-[10px] text-slate-400">
                              (~{( (sub.finalScore || sub.proposedScore) / 10 ).toFixed(1)}/10)
                            </div>
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3.5 text-center">
                        {sub.status === 'error' ? (
                          <span className="text-slate-400 text-[10px] font-mono">N/A</span>
                        ) : (
                          <span
                            className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ${
                              sub.confidence >= 0.9
                                ? 'bg-emerald-50 text-emerald-700'
                                : sub.confidence >= 0.8
                                ? 'bg-sky-50 text-sky-700'
                                : 'bg-amber-50 text-amber-700'
                            }`}
                          >
                            {(sub.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </td>

                      <td className="px-4 py-3.5">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium border ${badge.color}`}
                        >
                          <Icon className="w-3 h-3" />
                          <span>{badge.label}</span>
                        </span>
                      </td>

                      <td className="px-4 py-3.5 text-right">
                        <button
                          type="button"
                          onClick={() => onOpenReview(sub)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 text-white rounded-lg font-medium hover:bg-slate-800 transition-colors shadow-2xs"
                        >
                          <FileCheck2 className="w-3.5 h-3.5 text-sky-400" />
                          <span>Chấm bài</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Batch Publish Modal */}
      {showBatchModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md p-5 space-y-4">
            <div className="flex items-center gap-2.5 text-slate-900 border-b border-slate-100 pb-3">
              <Send className="w-5 h-5 text-emerald-600" />
              <h3 className="font-bold text-sm">Xác nhận công bố kết quả hàng loạt</h3>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Bạn đang chuẩn bị công bố chính thức kết quả cho{' '}
              <strong className="text-slate-900">{readyToPublishCount} bài nộp</strong> đã được duyệt. Sau khi công bố, sinh viên sẽ lập tức xem được điểm số, nhận xét và các bằng chứng đối chiếu.
            </p>

            <div className="p-3 bg-emerald-50 rounded-xl border border-emerald-200 text-emerald-800 text-xs">
              Mọi hành động công bố sẽ được ghi lại trong <strong>Audit Log</strong> theo quy định khảo thí.
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2 text-xs">
              <button
                type="button"
                onClick={() => setShowBatchModal(false)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={() => {
                  onBatchPublish();
                  setShowBatchModal(false);
                }}
                className="px-4 py-1.5 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-700"
              >
                Xác nhận công bố ngay
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
