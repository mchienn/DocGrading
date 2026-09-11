import React, { useState } from 'react';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  CheckCircle2,
  XCircle,
  Edit3,
  MessageSquare,
  Sparkles,
  AlertTriangle,
  Info,
  Send,
  Save,
  Clock,
  ShieldCheck,
  Search,
  BookOpen,
} from 'lucide-react';
import { Submission, Finding, CriterionResult } from '../../types/docgrading';

interface ReviewWorkspaceViewProps {
  submission: Submission;
  onBack: () => void;
  onApprove: (submissionId: string, updatedResults: CriterionResult[], finalScore: number) => void;
  onPublish: (submissionId: string) => void;
}

export const ReviewWorkspaceView: React.FC<ReviewWorkspaceViewProps> = ({
  submission,
  onBack,
  onApprove,
  onPublish,
}) => {
  // Navigation & Zoom
  const [currentPageIndex, setCurrentPageIndex] = useState<number>(0);
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  // Active criteria and findings
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(
    submission.criteriaResults[0]?.findings[0]?.id || null
  );

  // Edit / Override state
  const [criteriaState, setCriteriaState] = useState<CriterionResult[]>(
    submission.criteriaResults
  );
  const [showOverrideModal, setShowOverrideModal] = useState<boolean>(false);
  const [editingCriterion, setEditingCriterion] = useState<CriterionResult | null>(null);
  const [overrideLevel, setOverrideLevel] = useState<number>(3);
  const [overrideReason, setOverrideReason] = useState<string>('');
  const [overrideError, setOverrideError] = useState<string>('');

  // Comment library state
  const [activeCommentCriterionId, setActiveCommentCriterionId] = useState<string | null>(null);
  const commentBank = [
    'Tài liệu có cấu trúc rõ ràng, chuẩn phân cấp IEEE 830.',
    'Cần định lượng hóa các chỉ số hiệu năng (thời gian phản hồi < 2s).',
    'Chuẩn hóa tên gọi Actor đồng nhất trong toàn bộ kịch bản Use Case.',
    'Bổ sung mã ánh xạ còn thiếu trong bảng Ma trận truy vết (Traceability Matrix).',
  ];

  // Save status
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving'>('saved');

  // Helper: Calculate total score
  const calculateScore = (results: CriterionResult[]) => {
    let total = 0;
    results.forEach((r) => {
      // level 0..4, percent = level/4 * weight
      total += (r.confirmedLevel / 4) * r.weight;
    });
    // scale to 100 based on evaluated criteria weight
    const totalWeight = results.reduce((sum, r) => sum + r.weight, 0);
    if (totalWeight === 0) return 0;
    return (total / totalWeight) * 100;
  };

  const currentScore = calculateScore(criteriaState);

  // Current page object
  const pages = submission.pages.length > 0 ? submission.pages : [
    {
      pageNumber: 1,
      title: 'Tài liệu SRS — Xem trước PDF',
      content: ['Đang tải cấu trúc trang...'],
    },
  ];

  const currentPage = pages[currentPageIndex] || pages[0];

  // Helper to jump to page by finding
  const handleSelectFinding = (finding: Finding) => {
    setSelectedFindingId(finding.id);
    const pageIdx = pages.findIndex((p) => p.pageNumber === finding.pageNumber);
    if (pageIdx !== -1) {
      setCurrentPageIndex(pageIdx);
    }
  };

  // Open override dialog
  const openOverrideDialog = (criterion: CriterionResult) => {
    setEditingCriterion(criterion);
    setOverrideLevel(criterion.confirmedLevel);
    setOverrideReason(criterion.overrideReason || '');
    setOverrideError('');
    setShowOverrideModal(true);
  };

  // Confirm override
  const handleSaveOverride = () => {
    if (!overrideReason.trim()) {
      setOverrideError('Bắt buộc nhập lý do điều chỉnh điểm để lưu vào Audit Log.');
      return;
    }
    if (!editingCriterion) return;

    setSaveStatus('saving');
    setCriteriaState((prev) =>
      prev.map((c) =>
        c.criterionId === editingCriterion.criterionId
          ? {
              ...c,
              confirmedLevel: overrideLevel,
              overrideReason: overrideReason.trim(),
            }
          : c
      )
    );
    setTimeout(() => setSaveStatus('saved'), 400);
    setShowOverrideModal(false);
  };

  // Accept or reject finding
  const handleToggleFindingStatus = (findingId: string, newStatus: 'accepted' | 'rejected') => {
    setSaveStatus('saving');
    setCriteriaState((prev) =>
      prev.map((c) => ({
        ...c,
        findings: c.findings.map((f) =>
          f.id === findingId ? { ...f, status: newStatus } : f
        ),
      }))
    );
    setTimeout(() => setSaveStatus('saved'), 300);
  };

  // Add reusable comment
  const handleAddComment = (criterionId: string, comment: string) => {
    setSaveStatus('saving');
    setCriteriaState((prev) =>
      prev.map((c) =>
        c.criterionId === criterionId
          ? {
              ...c,
              teacherNotes: c.teacherNotes ? `${c.teacherNotes}\n• ${comment}` : `• ${comment}`,
            }
          : c
      )
    );
    setActiveCommentCriterionId(null);
    setTimeout(() => setSaveStatus('saved'), 300);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] overflow-hidden bg-slate-100">
      {/* Top Header Bar */}
      <div className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between shrink-0 shadow-2xs z-20">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-600"
            title="Quay lại hàng đợi"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="border-l border-slate-200 pl-3">
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm text-slate-900">{submission.studentName}</span>
              <span className="text-xs font-mono text-slate-400">({submission.studentCode})</span>
              <span className="text-xs px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-mono">
                {submission.fileName}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 text-xs text-slate-400">
            <span
              className={`w-2 h-2 rounded-full ${
                saveStatus === 'saved' ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse'
              }`}
            ></span>
            <span>{saveStatus === 'saved' ? 'Đã tự động lưu' : 'Đang lưu...'}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onApprove(submission.id, criteriaState, currentScore)}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors shadow-2xs"
            >
              <CheckCircle2 className="w-3.5 h-3.5 text-sky-400" />
              <span>Duyệt kết quả (Approve)</span>
            </button>

            <button
              type="button"
              onClick={() => onPublish(submission.id)}
              disabled={submission.status !== 'approved'}
              title={
                submission.status === 'approved'
                  ? 'Công bố kết quả'
                  : 'Duyệt kết quả trước khi công bố'
              }
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-2xs"
            >
              <Send className="w-3.5 h-3.5" />
              <span>Công bố kết quả (Publish)</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Split Screen */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT COLUMN: PDF Document Viewer (~65% width) */}
        <div className="flex-1 flex flex-col bg-slate-200/70 border-r border-slate-300/80 overflow-hidden">
          {/* PDF Toolbar */}
          <div className="h-11 bg-white border-b border-slate-200 px-4 flex items-center justify-between text-xs text-slate-600 shrink-0">
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={currentPageIndex === 0}
                onClick={() => setCurrentPageIndex((prev) => Math.max(0, prev - 1))}
                className="p-1 rounded hover:bg-slate-100 disabled:opacity-30"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="font-mono">
                Trang {currentPage.pageNumber} / {pages[pages.length - 1]?.pageNumber || pages.length}
              </span>
              <button
                type="button"
                disabled={currentPageIndex >= pages.length - 1}
                onClick={() => setCurrentPageIndex((prev) => Math.min(pages.length - 1, prev + 1))}
                className="p-1 rounded hover:bg-slate-100 disabled:opacity-30"
              >
                <ChevronRight className="w-4 h-4" />
              </button>

              <div className="h-4 w-px bg-slate-200 mx-1"></div>

              {/* Jump to page pills */}
              <div className="flex items-center gap-1 text-[11px]">
                <span className="text-slate-400">Chuyển nhanh:</span>
                {pages.map((p, idx) => (
                  <button
                    key={p.pageNumber}
                    type="button"
                    onClick={() => setCurrentPageIndex(idx)}
                    className={`px-1.5 py-0.5 rounded font-mono ${
                      currentPageIndex === idx
                        ? 'bg-slate-900 text-white'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    }`}
                  >
                    P{p.pageNumber}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setZoomLevel((prev) => Math.max(70, prev - 10))}
                className="p-1 rounded hover:bg-slate-100"
                title="Thu nhỏ"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="font-mono text-[11px] w-12 text-center">{zoomLevel}%</span>
              <button
                type="button"
                onClick={() => setZoomLevel((prev) => Math.min(150, prev + 10))}
                className="p-1 rounded hover:bg-slate-100"
                title="Phóng to"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setZoomLevel(100)}
                className="p-1 rounded hover:bg-slate-100"
                title="Khôi phục 100%"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* PDF Page Canvas Scrollable */}
          <div className="flex-1 overflow-y-auto p-6 flex justify-center items-start">
            <div
              style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}
              className="w-full max-w-2xl bg-white shadow-xl rounded-lg border border-slate-300 p-8 min-h-[780px] text-slate-800 transition-transform font-serif leading-relaxed relative"
            >
              {/* Watermark/header simulation */}
              <div className="border-b border-slate-200 pb-3 mb-6 flex items-center justify-between text-[11px] text-slate-400 font-sans">
                <span>DOCGRADING ACADEMIC VERIFICATION • SE302 SRS</span>
                <span className="font-mono">TRANG {currentPage.pageNumber}</span>
              </div>

              <h2 className="text-base font-bold text-slate-900 font-sans mb-4 border-b border-slate-100 pb-2">
                {currentPage.title}
              </h2>

              {/* Text content lines */}
              <div className="space-y-2 text-xs font-mono">
                {currentPage.content.map((line, idx) => {
                  // Check if this line matches an evidence snippet
                  const matchedFinding = criteriaState
                    .flatMap((c) => c.findings)
                    .find(
                      (f) =>
                        f.pageNumber === currentPage.pageNumber &&
                        (line.includes('Thủ kho') ||
                          line.includes('nhanh chóng và trực quan') ||
                          line.includes('Hủy phiếu nhập kho'))
                    );

                  const isSelected = matchedFinding && matchedFinding.id === selectedFindingId;

                  return (
                    <div
                      key={idx}
                      className={`p-1.5 rounded transition-all ${
                        matchedFinding
                          ? isSelected
                            ? 'bg-amber-100 border-l-4 border-amber-500 font-bold shadow-xs cursor-pointer'
                            : 'bg-amber-50/70 border-l-2 border-amber-300 cursor-pointer hover:bg-amber-100/80'
                          : 'hover:bg-slate-50'
                      }`}
                      onClick={() => matchedFinding && handleSelectFinding(matchedFinding)}
                    >
                      {matchedFinding && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-sans font-semibold text-amber-700 bg-amber-200/80 px-1.5 py-0.2 rounded mr-2 uppercase">
                          Bằng chứng {matchedFinding.severity}
                        </span>
                      )}
                      <span>{line}</span>
                    </div>
                  );
                })}
              </div>

              {/* Page footer */}
              <div className="absolute bottom-4 left-8 right-8 pt-3 border-t border-slate-200 flex items-center justify-between text-[10px] text-slate-400 font-sans">
                <span>Tài liệu: {submission.fileName}</span>
                <span>Hệ thống chấm DocGrading</span>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Criteria & Findings Review Panel (~35% width, min 380px) */}
        <div className="w-[420px] bg-white border-l border-slate-200 flex flex-col overflow-hidden shrink-0">
          {/* Proposed Score Header */}
          <div className="p-4 bg-slate-900 text-white flex items-center justify-between shrink-0">
            <div>
              <span className="text-[11px] text-sky-400 uppercase font-bold tracking-wider">
                Điểm đề xuất (AI & Rule Engine)
              </span>
              <div className="flex items-baseline gap-2 mt-0.5">
                <span className="text-2xl font-black font-mono tracking-tight text-white">
                  {currentScore.toFixed(1)}
                </span>
                <span className="text-xs text-slate-400">/ 100</span>
                <span className="text-xs font-mono text-slate-300">
                  (~{(currentScore / 10).toFixed(2)}/10)
                </span>
              </div>
            </div>

            <div className="text-right">
              <span className="text-[10px] text-slate-400 block">Độ tin cậy</span>
              <span className="inline-block px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-sky-500/20 text-sky-300 border border-sky-400/30">
                {(submission.confidence * 100).toFixed(0)}% Tin cậy cao
              </span>
            </div>
          </div>

          {/* Criteria & Findings Tabs / List */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-900 uppercase text-[11px] tracking-wider">
                Chi tiết đánh giá theo tiêu chí ({criteriaState.length})
              </span>
              <span className="text-[11px] text-slate-500">Mức 0 – 4</span>
            </div>

            <div className="space-y-3">
              {criteriaState.map((res) => {
                const isOverridden = res.confirmedLevel !== res.proposedLevel;
                return (
                  <div
                    key={res.criterionId}
                    className="p-3 rounded-xl border border-slate-200 bg-slate-50/60 hover:bg-slate-50 transition-all space-y-2.5 shadow-2xs"
                  >
                    {/* Criterion Title & Level */}
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-slate-800 text-xs">
                            {res.criterionName}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-500">Trọng số: {res.weight}%</span>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <div className="text-right">
                          <div className="flex items-center gap-1">
                            <span className="text-xs font-bold font-mono text-slate-900">
                              Mức {res.confirmedLevel}/4
                            </span>
                            {isOverridden && (
                              <span className="text-[10px] text-amber-600 font-mono font-semibold">
                                (Sửa từ {res.proposedLevel})
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-400">
                            {((res.confirmedLevel / 4) * res.weight).toFixed(1)}%
                          </span>
                        </div>

                        <button
                          type="button"
                          onClick={() => openOverrideDialog(res)}
                          className="p-1 rounded-md hover:bg-slate-200 text-slate-600"
                          title="Điều chỉnh điểm"
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    {/* Override reason badge if exists */}
                    {res.overrideReason && (
                      <div className="p-2 rounded-lg bg-amber-50 text-amber-800 border border-amber-200 text-[11px]">
                        <strong>Lý do điều chỉnh:</strong> {res.overrideReason}
                      </div>
                    )}

                    {/* Findings list under this criterion */}
                    {res.findings.length > 0 && (
                      <div className="space-y-2 pt-1 border-t border-slate-200/80">
                        {res.findings.map((finding) => {
                          const isSelected = selectedFindingId === finding.id;
                          const isRejected = finding.status === 'rejected';

                          return (
                            <div
                              key={finding.id}
                              onClick={() => handleSelectFinding(finding)}
                              className={`p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                                isSelected
                                  ? 'border-sky-500 bg-sky-50/70 shadow-xs'
                                  : isRejected
                                  ? 'border-slate-200 bg-slate-100 opacity-60'
                                  : 'border-slate-200 bg-white hover:border-slate-300'
                              }`}
                            >
                              <div className="flex items-center justify-between gap-1 mb-1">
                                <div className="flex items-center gap-1.5">
                                  <span
                                    className={`px-1.5 py-0.2 rounded text-[10px] font-bold uppercase ${
                                      finding.severity === 'critical'
                                        ? 'bg-rose-100 text-rose-700'
                                        : finding.severity === 'major'
                                        ? 'bg-amber-100 text-amber-700'
                                        : 'bg-blue-100 text-blue-700'
                                    }`}
                                  >
                                    {finding.severity}
                                  </span>
                                  <span className="font-semibold text-slate-900 text-xs">
                                    {finding.title}
                                  </span>
                                </div>
                                <span className="text-[10px] font-mono text-slate-400 shrink-0">
                                  P.{finding.pageNumber}
                                </span>
                              </div>

                              <p className="text-[11px] text-slate-600 leading-relaxed mb-1.5">
                                {finding.description}
                              </p>

                              <div className="p-1.5 bg-slate-50 rounded border border-slate-200/60 text-[11px] text-sky-800">
                                <span className="font-semibold">Gợi ý sửa:</span> {finding.suggestion}
                              </div>

                              {/* Action: Accept / Reject finding */}
                              <div className="mt-2 pt-1.5 border-t border-slate-100 flex items-center justify-between text-[11px]">
                                <span className="text-slate-400 font-mono">
                                  {(finding.confidence * 100).toFixed(0)}% tin cậy
                                </span>
                                <div className="flex items-center gap-1">
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleToggleFindingStatus(finding.id, 'accepted');
                                    }}
                                    className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                      finding.status === 'accepted'
                                        ? 'bg-emerald-100 text-emerald-800 font-bold'
                                        : 'hover:bg-slate-100 text-slate-600'
                                    }`}
                                  >
                                    Chấp nhận
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleToggleFindingStatus(finding.id, 'rejected');
                                    }}
                                    className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                      finding.status === 'rejected'
                                        ? 'bg-rose-100 text-rose-800 font-bold'
                                        : 'hover:bg-slate-100 text-slate-600'
                                    }`}
                                  >
                                    Bác bỏ
                                  </button>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Teacher Notes / Comments */}
                    {res.teacherNotes && (
                      <div className="p-2 rounded bg-white border border-slate-200 text-[11px] text-slate-700 whitespace-pre-line">
                        <strong className="text-slate-900 block mb-0.5">Nhận xét của giảng viên:</strong>
                        {res.teacherNotes}
                      </div>
                    )}

                    {/* Reusable Comment Library Trigger */}
                    <div className="pt-1 flex items-center justify-between text-[11px]">
                      <button
                        type="button"
                        onClick={() =>
                          setActiveCommentCriterionId(
                            activeCommentCriterionId === res.criterionId ? null : res.criterionId
                          )
                        }
                        className="text-sky-600 hover:text-sky-700 font-medium inline-flex items-center gap-1"
                      >
                        <MessageSquare className="w-3 h-3" />
                        <span>Thêm nhận xét mẫu</span>
                      </button>
                    </div>

                    {/* Reusable comment drawer */}
                    {activeCommentCriterionId === res.criterionId && (
                      <div className="p-2 bg-white rounded-lg border border-slate-200 space-y-1.5">
                        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">
                          Thư viện mẫu nhận xét nhanh:
                        </span>
                        {commentBank.map((c, idx) => (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => handleAddComment(res.criterionId, c)}
                            className="w-full text-left p-1.5 rounded hover:bg-slate-50 text-[11px] text-slate-700 border border-slate-100 block"
                          >
                            + {c}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Override Score Dialog */}
      {showOverrideModal && editingCriterion && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-md p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Edit3 className="w-4 h-4 text-sky-600" />
                <h3 className="font-bold text-sm text-slate-900">
                  Điều chỉnh điểm tiêu chí: {editingCriterion.criterionName}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowOverrideModal(false)}
                className="text-slate-400 hover:text-slate-700 text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  Chọn mức đánh giá (0 = Chưa đạt, 4 = Xuất sắc)
                </label>
                <div className="grid grid-cols-5 gap-2">
                  {[0, 1, 2, 3, 4].map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      onClick={() => setOverrideLevel(lvl)}
                      className={`py-2 rounded-lg font-bold font-mono text-sm border transition-all ${
                        overrideLevel === lvl
                          ? 'bg-slate-900 text-white border-slate-900 shadow-xs'
                          : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      Mức {lvl}
                    </button>
                  ))}
                </div>
                <div className="flex items-center justify-between text-[11px] text-slate-400 mt-1">
                  <span>Mức đề xuất AI: {editingCriterion.proposedLevel}/4</span>
                  <span>
                    Điểm tính: {((overrideLevel / 4) * editingCriterion.weight).toFixed(1)} /{' '}
                    {editingCriterion.weight}%
                  </span>
                </div>
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  Lý do điều chỉnh (Bắt buộc theo quy định kiểm toán) <span className="text-rose-500">*</span>
                </label>
                <textarea
                  rows={3}
                  required
                  placeholder="Ghi rõ căn cứ (VD: Sinh viên đã bổ sung đầy đủ chỉ số hiệu năng ở phần phụ lục)..."
                  value={overrideReason}
                  onChange={(e) => {
                    setOverrideReason(e.target.value);
                    if (overrideError) setOverrideError('');
                  }}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 leading-relaxed"
                />
                {overrideError && <p className="text-[11px] text-rose-600 mt-1">{overrideError}</p>}
              </div>

              <div className="p-2.5 bg-amber-50 rounded-lg border border-amber-200 text-amber-800 text-[11px]">
                Hệ thống sẽ lưu vết hành động này vào <strong>Audit Log</strong> với mã giảng viên và thời điểm can thiệp.
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowOverrideModal(false)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleSaveOverride}
                className="px-4 py-1.5 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800"
              >
                Lưu điều chỉnh
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
