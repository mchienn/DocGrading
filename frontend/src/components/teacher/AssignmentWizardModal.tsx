import React, { useState } from 'react';
import {
  Check,
  CheckCircle2,
  FileText,
  AlertTriangle,
  Sliders,
  Calendar,
  Layers,
  ArrowRight,
  ArrowLeft,
  X,
} from 'lucide-react';
import { Assignment, Course, RubricCriterion } from '../../types/docgrading';
import { DEFAULT_SRS_CRITERIA } from '../../data/mockData';

interface AssignmentWizardModalProps {
  course: Course;
  onClose: () => void;
  onSaveAssignment: (assignment: Partial<Assignment>) => void;
  initialAssignment?: Assignment | null;
}

export const AssignmentWizardModal: React.FC<AssignmentWizardModalProps> = ({
  course,
  onClose,
  onSaveAssignment,
  initialAssignment,
}) => {
  const [step, setStep] = useState<number>(1);

  // Form states
  const [title, setTitle] = useState(initialAssignment?.title || '');
  const [description, setDescription] = useState(
    initialAssignment?.description ||
      'Nộp bản thảo tài liệu SRS đầy đủ cấu trúc 3 phần theo chuẩn IEEE 830. Hệ thống DocGrading sẽ phân tích cú pháp, bảng biểu và đề xuất điểm cho giảng viên duyệt.'
  );
  const [dueDate, setDueDate] = useState(
    initialAssignment?.dueDate || '2026-09-25T23:59:00'
  );
  const [maxSubmissions, setMaxSubmissions] = useState(initialAssignment?.maxSubmissions || 3);
  const [maxFileSizeMb, setMaxFileSizeMb] = useState(initialAssignment?.requirements.maxFileSizeMb || 25);
  const [minPages, setMinPages] = useState(initialAssignment?.requirements.minPages || 15);
  const [maxPages, setMaxPages] = useState(initialAssignment?.requirements.maxPages || 60);
  const [textLayerRequired, setTextLayerRequired] = useState(true);
  const [criteria, setCriteria] = useState<RubricCriterion[]>(
    initialAssignment?.criteria || DEFAULT_SRS_CRITERIA
  );

  // Weight validation
  const totalWeight = criteria.reduce((sum, c) => sum + c.weight, 0);
  const isWeightValid = totalWeight === 100;

  const handleUpdateWeight = (id: string, newWeight: number) => {
    setCriteria((prev) =>
      prev.map((c) => (c.id === id ? { ...c, weight: Math.max(0, newWeight) } : c))
    );
  };

  const handleComplete = (status: 'draft' | 'open') => {
    if (!title) {
      setStep(1);
      return;
    }
    if (!isWeightValid) {
      setStep(3);
      return;
    }

    onSaveAssignment({
      id: initialAssignment?.id || `ASM-${Date.now()}`,
      courseId: course.id,
      courseCode: course.code,
      courseName: course.name,
      title,
      description,
      dueDate,
      maxSubmissions,
      status,
      submittedCount: initialAssignment?.submittedCount || 0,
      reviewedCount: initialAssignment?.reviewedCount || 0,
      publishedCount: initialAssignment?.publishedCount || 0,
      rubricId: 'RUBRIC-SRS-DEFAULT',
      requirements: {
        allowedFormat: 'PDF',
        maxFileSizeMb,
        minPages,
        maxPages,
        textLayerRequired,
        templateProvided: true,
      },
      criteria,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-3xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Modal Top Bar */}
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/50">
          <div>
            <span className="text-[11px] font-mono font-medium text-slate-500 uppercase tracking-wider">
              {course.code} — Wizard tạo đợt nộp bài
            </span>
            <h2 className="text-base font-bold text-slate-900">
              {initialAssignment ? 'Chỉnh sửa đợt nộp bài tập' : 'Cấu hình đợt nộp báo cáo SRS mới'}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="px-6 py-3 bg-white border-b border-slate-100 flex items-center justify-between text-xs">
          {[
            { num: 1, label: 'Thông tin chung' },
            { num: 2, label: 'Yêu cầu nộp PDF' },
            { num: 3, label: 'Cấu hình Rubric' },
            { num: 4, label: 'Xem lại & Công bố' },
          ].map((s) => (
            <div
              key={s.num}
              onClick={() => setStep(s.num)}
              className={`flex items-center gap-2 cursor-pointer transition-colors ${
                step === s.num
                  ? 'text-slate-900 font-semibold'
                  : step > s.num
                  ? 'text-emerald-600 font-medium'
                  : 'text-slate-400'
              }`}
            >
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                  step === s.num
                    ? 'bg-slate-900 text-white'
                    : step > s.num
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-slate-100 text-slate-500'
                }`}
              >
                {step > s.num ? <Check className="w-3.5 h-3.5" /> : s.num}
              </div>
              <span className="hidden sm:inline">{s.label}</span>
            </div>
          ))}
        </div>

        {/* Step Content */}
        <div className="p-6 overflow-y-auto space-y-4 flex-1 text-xs">
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  Tiêu đề đợt nộp báo cáo <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="VD: Đặc tả Yêu cầu Phần mềm (SRS) - Đợt 1"
                  className="w-full px-3.5 py-2.5 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 text-sm"
                />
              </div>

              <div>
                <label className="block text-slate-700 font-medium mb-1">Mô tả & Hướng dẫn sinh viên</label>
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Hướng dẫn cấu trúc, các phần cần nhấn mạnh..."
                  className="w-full px-3.5 py-2.5 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 leading-relaxed"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-700 font-medium mb-1 flex items-center gap-1.5">
                    <Calendar className="w-3.5 h-3.5 text-slate-400" />
                    <span>Hạn chót nộp bài (Deadline)</span>
                  </label>
                  <input
                    type="datetime-local"
                    value={dueDate.slice(0, 16)}
                    onChange={(e) => setDueDate(e.target.value)}
                    className="w-full px-3.5 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-700 font-medium mb-1">Số lần nộp tối đa</label>
                  <select
                    value={maxSubmissions}
                    onChange={(e) => setMaxSubmissions(Number(e.target.value))}
                    className="w-full px-3.5 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500 bg-white"
                  >
                    <option value={1}>1 lần (Không nộp lại)</option>
                    <option value={2}>2 lần</option>
                    <option value={3}>3 lần (Khuyên dùng)</option>
                    <option value={5}>5 lần</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <div className="p-3.5 bg-sky-50 rounded-xl border border-sky-100 flex items-start gap-3">
                <FileText className="w-5 h-5 text-sky-600 shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-semibold text-sky-900">Quy chuẩn file đầu vào DocGrading</h4>
                  <p className="text-sky-700 mt-0.5 leading-relaxed">
                    Hệ thống trích xuất Document IR tự động bằng pypdf và pdfplumber. Chỉ chấp nhận định dạng PDF text-native, tự động từ chối tài liệu scan để đảm bảo độ chính xác bằng chứng.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Dung lượng tối đa (MB)</label>
                  <input
                    type="number"
                    value={maxFileSizeMb}
                    onChange={(e) => setMaxFileSizeMb(Number(e.target.value))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Số trang tối thiểu</label>
                  <input
                    type="number"
                    value={minPages}
                    onChange={(e) => setMinPages(Number(e.target.value))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500"
                  />
                </div>
                <div>
                  <label className="block text-slate-700 font-medium mb-1">Số trang tối đa</label>
                  <input
                    type="number"
                    value={maxPages}
                    onChange={(e) => setMaxPages(Number(e.target.value))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-sky-500"
                  />
                </div>
              </div>

              <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={textLayerRequired}
                    onChange={(e) => setTextLayerRequired(e.target.checked)}
                    className="rounded border-slate-300 text-sky-600 focus:ring-sky-500"
                  />
                  <span className="font-medium text-slate-800">
                    Bắt buộc có text layer (Từ chối PDF scan không OCR)
                  </span>
                </label>
                <p className="text-[11px] text-slate-500 pl-5">
                  Khi sinh viên upload file, worker Celery sẽ quét mật độ text layer. Nếu phát hiện trang scan, hệ thống sẽ báo lỗi và yêu cầu xuất lại file PDF.
                </p>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                <div>
                  <h4 className="font-bold text-slate-900">Rubric 12 tiêu chí SRS IEEE 830</h4>
                  <p className="text-slate-500 text-[11px]">
                    Thang điểm mức 0–4. Điểm phần trăm = (mức / 4) × trọng số.
                  </p>
                </div>
                <div
                  className={`px-3 py-1 rounded-lg text-xs font-bold font-mono ${
                    isWeightValid
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : 'bg-rose-50 text-rose-700 border border-rose-200'
                  }`}
                >
                  Tổng trọng số: {totalWeight}% / 100%
                </div>
              </div>

              {!isWeightValid && (
                <div className="p-2.5 bg-rose-50 rounded-lg border border-rose-200 text-rose-700 flex items-center gap-2 text-xs">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>Tổng trọng số phải bằng chính xác 100% để đảm bảo tính điểm chính xác.</span>
                </div>
              )}

              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {criteria.map((c) => (
                  <div
                    key={c.id}
                    className="p-3 bg-slate-50 rounded-lg border border-slate-200/80 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-slate-700">{c.code}</span>
                        <span className="font-medium text-slate-900 truncate">{c.name}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 font-mono">
                          {c.defaultEvaluator}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 truncate mt-0.5">{c.description}</p>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-slate-500">Trọng số:</span>
                      <input
                        type="number"
                        min={1}
                        max={50}
                        value={c.weight}
                        onChange={(e) => handleUpdateWeight(c.id, Number(e.target.value))}
                        className="w-16 px-2 py-1 border border-slate-300 rounded text-center font-bold bg-white"
                      />
                      <span className="text-slate-600 font-medium">%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 space-y-3">
                <h4 className="font-bold text-slate-900 text-sm">Xác nhận thông tin đợt nộp</h4>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-slate-400 block">Môn học:</span>
                    <span className="font-medium text-slate-800">
                      {course.code} — {course.name}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Tiêu đề:</span>
                    <span className="font-semibold text-slate-900">{title || '(Chưa nhập)'}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Hạn chót:</span>
                    <span className="font-medium text-slate-800">
                      {new Date(dueDate).toLocaleString('vi-VN')}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Định dạng file:</span>
                    <span className="font-medium text-slate-800">
                      PDF text-layer, tối đa {maxFileSizeMb}MB, {minPages}-{maxPages} trang
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Rubric:</span>
                    <span className="font-medium text-emerald-700">12 tiêu chí IEEE 830 (100%)</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Cơ chế chấm:</span>
                    <span className="font-medium text-slate-800">
                      AI & Rule đề xuất → Giảng viên duyệt & công bố
                    </span>
                  </div>
                </div>
              </div>

              <div className="p-3 bg-amber-50 rounded-xl border border-amber-200 text-amber-800 text-xs">
                <strong>Lưu ý nghiệp vụ:</strong> Sau khi công bố đợt nộp, rubric sẽ được khóa bất biến để đảm bảo tính công bằng cho tất cả các lượt nộp của sinh viên.
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="px-6 py-3.5 border-t border-slate-200 flex items-center justify-between bg-slate-50/50">
          <div>
            {step > 1 && (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 text-xs font-medium"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Quay lại</span>
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleComplete('draft')}
              className="px-3.5 py-1.5 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-100 text-xs font-medium"
            >
              Lưu bản nháp (Draft)
            </button>

            {step < 4 ? (
              <button
                type="button"
                onClick={() => setStep(step + 1)}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800"
              >
                <span>Tiếp tục</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => handleComplete('open')}
                disabled={!isWeightValid || !title}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 disabled:opacity-50"
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Công bố đợt nộp bài</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
