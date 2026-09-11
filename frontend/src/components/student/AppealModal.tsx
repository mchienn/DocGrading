import React, { useState } from 'react';
import { MessageSquare, X, Send, AlertCircle } from 'lucide-react';
import { Submission, ReviewAppeal } from '../../types/docgrading';

interface AppealModalProps {
  submission: Submission;
  onClose: () => void;
  onSubmitAppeal: (appeal: Partial<ReviewAppeal>) => void;
}

export const AppealModal: React.FC<AppealModalProps> = ({
  submission,
  onClose,
  onSubmitAppeal,
}) => {
  const [selectedCriterionId, setSelectedCriterionId] = useState(
    submission.criteriaResults[0]?.criterionId || 'CRT-01'
  );
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  const selectedCriterion = submission.criteriaResults.find(
    (c) => c.criterionId === selectedCriterionId
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) {
      setError('Vui lòng nêu rõ lý do và căn cứ trong tài liệu cần xem lại.');
      return;
    }

    onSubmitAppeal({
      id: `APL-${Date.now()}`,
      submissionId: submission.id,
      studentName: submission.studentName,
      studentCode: submission.studentCode,
      criterionId: selectedCriterionId,
      criterionName: selectedCriterion?.criterionName || 'Tiêu chí đánh giá',
      reason: reason.trim(),
      status: 'pending',
      createdAt: 'Vừa xong',
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-md p-5 space-y-4 text-xs">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-sky-600" />
            <h3 className="font-bold text-sm text-slate-900">Gửi yêu cầu phúc khảo / Xem lại</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-slate-700 font-medium mb-1">
              Chọn tiêu chí cần xem xét lại:
            </label>
            <select
              value={selectedCriterionId}
              onChange={(e) => setSelectedCriterionId(e.target.value)}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white text-slate-800 focus:outline-hidden focus:ring-1 focus:ring-sky-500"
            >
              {submission.criteriaResults.map((c) => (
                <option key={c.criterionId} value={c.criterionId}>
                  {c.criterionName} (Mức {c.confirmedLevel}/4)
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-slate-700 font-medium mb-1">
              Lý do và vị trí bằng chứng trong tài liệu PDF:
            </label>
            <textarea
              rows={4}
              required
              placeholder="VD: Em đã bổ sung sơ đồ sequence diagram tại phụ lục trang 36, xin thầy xem xét lại điểm tiêu chí này..."
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                if (error) setError('');
              }}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 leading-relaxed"
            />
            {error && <p className="text-[11px] text-rose-600 mt-1">{error}</p>}
          </div>

          <div className="p-3 bg-sky-50 rounded-xl border border-sky-200 text-sky-900 leading-relaxed">
            Mỗi bài nộp chỉ được gửi <strong>01 yêu cầu phúc khảo</strong>. Giảng viên sẽ nhận được thông báo trực tiếp trong hộp thư review.
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
            >
              Hủy
            </button>
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800"
            >
              <Send className="w-3.5 h-3.5" />
              <span>Gửi yêu cầu phúc khảo</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
