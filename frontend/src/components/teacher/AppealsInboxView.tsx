import React, { useState } from 'react';
import { Inbox, CheckCircle2, XCircle, MessageSquare, Clock, User, ArrowRight } from 'lucide-react';
import { ReviewAppeal } from '../../types/docgrading';

interface AppealsInboxViewProps {
  appeals: ReviewAppeal[];
  onRespondAppeal: (appealId: string, response: string, newStatus: 'resolved' | 'rejected') => void;
}

export const AppealsInboxView: React.FC<AppealsInboxViewProps> = ({
  appeals,
  onRespondAppeal,
}) => {
  const [selectedAppeal, setSelectedAppeal] = useState<ReviewAppeal | null>(null);
  const [responseText, setResponseText] = useState('');
  const [resolutionStatus, setResolutionStatus] = useState<'resolved' | 'rejected'>('resolved');

  const handleOpenRespond = (appeal: ReviewAppeal) => {
    setSelectedAppeal(appeal);
    setResponseText(appeal.teacherResponse || '');
    setResolutionStatus(appeal.status === 'rejected' ? 'rejected' : 'resolved');
  };

  const handleSaveResponse = () => {
    if (!selectedAppeal || !responseText.trim()) return;
    onRespondAppeal(selectedAppeal.id, responseText.trim(), resolutionStatus);
    setSelectedAppeal(null);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900">Hộp thư Yêu cầu Phúc khảo & Xem lại (Appeals)</h1>
        <p className="text-xs text-slate-500 mt-1">
          Tiếp nhận khiếu nại của sinh viên về tiêu chí đánh giá, đối chiếu bằng chứng và đưa ra quyết định phúc khảo.
        </p>
      </div>

      {/* Appeals Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
              <tr>
                <th className="px-4 py-3">Sinh viên</th>
                <th className="px-4 py-3">Tiêu chí khiếu nại</th>
                <th className="px-4 py-3">Nội dung khiếu nại</th>
                <th className="px-4 py-3">Thời điểm</th>
                <th className="px-4 py-3">Trạng thái</th>
                <th className="px-4 py-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {appeals.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                    Không có yêu cầu phúc khảo nào cần xử lý.
                  </td>
                </tr>
              ) : (
                appeals.map((appeal) => (
                  <tr key={appeal.id} className="hover:bg-slate-50/70 transition-colors">
                    <td className="px-4 py-3.5">
                      <div className="font-semibold text-slate-900">{appeal.studentName}</div>
                      <div className="text-[11px] text-slate-400 font-mono">MSSV: {appeal.studentCode}</div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="font-medium text-slate-800">{appeal.criterionName}</span>
                    </td>
                    <td className="px-4 py-3.5 max-w-sm">
                      <p className="text-slate-600 line-clamp-2 leading-relaxed">{appeal.reason}</p>
                      {appeal.teacherResponse && (
                        <p className="text-[11px] text-emerald-700 mt-1 font-medium bg-emerald-50 p-1.5 rounded">
                          Phản hồi: {appeal.teacherResponse}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-slate-500 whitespace-nowrap">
                      {appeal.createdAt}
                    </td>
                    <td className="px-4 py-3.5">
                      {appeal.status === 'resolved' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Đã giải quyết</span>
                        </span>
                      ) : appeal.status === 'rejected' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
                          <XCircle className="w-3 h-3" />
                          <span>Bác bỏ</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                          <Clock className="w-3 h-3" />
                          <span>Chờ phản hồi</span>
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button
                        type="button"
                        onClick={() => handleOpenRespond(appeal)}
                        className="px-3 py-1.5 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800"
                      >
                        {appeal.status === 'pending' ? 'Xử lý phúc khảo' : 'Xem chi tiết'}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Response Modal */}
      {selectedAppeal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-lg p-5 space-y-4 text-xs">
            <div className="border-b border-slate-100 pb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MessageSquare className="w-4 h-4 text-sky-600" />
                <h3 className="font-bold text-sm text-slate-900">
                  Xử lý yêu cầu phúc khảo của {selectedAppeal.studentName}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedAppeal(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 space-y-1.5">
                <span className="text-slate-400 text-[10px] block uppercase font-bold">
                  Tiêu chí khiếu nại:
                </span>
                <p className="font-semibold text-slate-900">{selectedAppeal.criterionName}</p>
                <span className="text-slate-400 text-[10px] block uppercase font-bold mt-2">
                  Lý do của sinh viên:
                </span>
                <p className="text-slate-700 leading-relaxed">{selectedAppeal.reason}</p>
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">Quyết định xử lý:</label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setResolutionStatus('resolved')}
                    className={`flex-1 py-2 rounded-lg font-medium border text-center transition-all ${
                      resolutionStatus === 'resolved'
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300 font-bold'
                        : 'bg-white text-slate-700 border-slate-200'
                    }`}
                  >
                    Chấp thuận & Điều chỉnh
                  </button>
                  <button
                    type="button"
                    onClick={() => setResolutionStatus('rejected')}
                    className={`flex-1 py-2 rounded-lg font-medium border text-center transition-all ${
                      resolutionStatus === 'rejected'
                        ? 'bg-rose-50 text-rose-700 border-rose-300 font-bold'
                        : 'bg-white text-slate-700 border-slate-200'
                    }`}
                  >
                    Giữ nguyên điểm
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  Nhận xét giải thích cho sinh viên:
                </label>
                <textarea
                  rows={3}
                  required
                  value={responseText}
                  onChange={(e) => setResponseText(e.target.value)}
                  placeholder="Ghi rõ lý do và chỉ dẫn cho sinh viên..."
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 leading-relaxed"
                />
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setSelectedAppeal(null)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={handleSaveResponse}
                className="px-4 py-1.5 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800"
              >
                Gửi phản hồi phúc khảo
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
