import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  FileText,
  CheckCircle2,
  AlertTriangle,
  ArrowLeft,
  Clock,
  Sparkles,
  ShieldCheck,
  X,
} from 'lucide-react';
import { Assignment, Submission } from '../../types/docgrading';

interface StudentUploadViewProps {
  assignment: Assignment;
  onBack: () => void;
  onSubmitSuccess: (newSubmission: Submission) => void;
}

export const StudentUploadView: React.FC<StudentUploadViewProps> = ({
  assignment,
  onBack,
  onSubmitSuccess,
}) => {
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    pageCount: number;
    textDensity: number;
    hasScanWarning: boolean;
    errorMsg?: string;
  } | null>(null);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const processFile = (uploadedFile: File) => {
    setFile(uploadedFile);
    setValidationResult(null);

    // Step 1: Check format
    if (!uploadedFile.name.toLowerCase().endsWith('.pdf')) {
      setValidationResult({
        valid: false,
        pageCount: 0,
        textDensity: 0,
        hasScanWarning: false,
        errorMsg: 'Định dạng không hợp lệ. Hệ thống DocGrading chỉ chấp nhận file định dạng .PDF.',
      });
      return;
    }

    // Step 1.2: Check size
    const sizeMb = uploadedFile.size / (1024 * 1024);
    if (sizeMb > assignment.requirements.maxFileSizeMb) {
      setValidationResult({
        valid: false,
        pageCount: 0,
        textDensity: 0,
        hasScanWarning: false,
        errorMsg: `Dung lượng file (${sizeMb.toFixed(1)}MB) vượt quá giới hạn cho phép (${assignment.requirements.maxFileSizeMb}MB).`,
      });
      return;
    }

    // Step 2: Simulate native text layer validation (Worker Document IR)
    setIsValidating(true);
    setTimeout(() => {
      setIsValidating(false);
      // If filename contains "scan", simulate scan warning
      const isScan = uploadedFile.name.toLowerCase().includes('scan');
      if (isScan) {
        setValidationResult({
          valid: false,
          pageCount: 24,
          textDensity: 12,
          hasScanWarning: true,
          errorMsg:
            'Phát hiện PDF scan: Các trang không có text layer native. Vui lòng xuất lại file PDF từ Microsoft Word hoặc LaTeX bằng chức năng "Save as PDF" / "Export", không nộp bản scan/chụp ảnh.',
        });
      } else {
        setValidationResult({
          valid: true,
          pageCount: 38,
          textDensity: 98,
          hasScanWarning: false,
        });
      }
    }, 1200);
  };

  const handleConfirmSubmit = () => {
    if (!file || !validationResult?.valid) return;

    setIsSubmitting(true);
    let progress = 10;
    const interval = setInterval(() => {
      progress += 25;
      if (progress >= 100) {
        clearInterval(interval);
        setUploadProgress(100);

        setTimeout(() => {
          const newSub: Submission = {
            id: `SUB-${Date.now().toString().slice(-4)}`,
            assignmentId: assignment.id,
            assignmentTitle: assignment.title,
            courseCode: assignment.courseCode,
            studentId: 'USR-STUDENT-01',
            studentName: 'Đỗ Minh Trí',
            studentCode: '20214567',
            version: 1,
            fileName: file.name,
            fileSize: `${(file.size / (1024 * 1024)).toFixed(1)} MB`,
            pageCount: validationResult.pageCount || 36,
            submittedAt: 'Vừa xong',
            status: 'evaluating',
            proposedScore: 84.0,
            confidence: 0.94,
            criteriaResults: [],
            pages: [
              {
                pageNumber: 1,
                title: 'Trang bìa & Thông tin đề tài',
                content: [
                  'TRƯỜNG ĐẠI HỌC BÁCH KHOA HÀ NỘI',
                  `BÁO CÁO ĐẶC TẢ YÊU CẦU PHẦN MỀM: ${assignment.title}`,
                  'Sinh viên: Đỗ Minh Trí — MSSV: 20214567',
                ],
              },
            ],
          };

          setIsSubmitting(false);
          onSubmitSuccess(newSub);
        }, 500);
      } else {
        setUploadProgress(progress);
      }
    }, 200);
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Back button */}
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Quay lại danh sách đợt nộp</span>
      </button>

      {/* Hero Header */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs">
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded-md bg-sky-50 text-sky-700 font-mono text-xs font-bold border border-sky-200/80">
            {assignment.courseCode}
          </span>
          <span className="text-xs text-slate-500">{assignment.courseName}</span>
        </div>
        <h1 className="text-lg font-bold text-slate-900 mt-1">{assignment.title}</h1>
        <p className="text-xs text-slate-500 mt-1">
          Hệ thống sẽ thực hiện kiểm tra 2 bước: Kiểm tra kích thước file và Quét lớp văn bản (text layer) native.
        </p>
      </div>

      {/* Upload Box */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-2xs space-y-5">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          onChange={handleChange}
          className="hidden"
        />

        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all ${
            dragActive
              ? 'border-sky-500 bg-sky-50/50'
              : file
              ? 'border-slate-300 bg-slate-50/60'
              : 'border-slate-300 hover:border-slate-400 bg-slate-50/30'
          }`}
        >
          <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center text-slate-600 mx-auto mb-3">
            <UploadCloud className="w-6 h-6 text-sky-600" />
          </div>

          <h3 className="text-sm font-bold text-slate-900">
            {file ? file.name : 'Kéo thả file PDF vào đây hoặc bấm để chọn'}
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            Chỉ nhận file PDF có text layer • Tối đa {assignment.requirements.maxFileSizeMb}MB
          </p>

          <button
            type="button"
            className="mt-4 px-4 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Chọn file từ máy tính
          </button>
        </div>

        {/* Validation Loading state */}
        {isValidating && (
          <div className="p-4 bg-sky-50 rounded-xl border border-sky-100 flex items-center gap-3 text-xs text-sky-800">
            <div className="w-4 h-4 border-2 border-sky-600 border-t-transparent rounded-full animate-spin"></div>
            <div>
              <p className="font-semibold">Đang phân tích cấu trúc Document IR & Text Layer...</p>
              <p className="text-sky-600 text-[11px]">
                Kiểm tra mật độ vector chữ và xác nhận không có trang scan.
              </p>
            </div>
          </div>
        )}

        {/* Validation Result */}
        {validationResult && (
          <div
            className={`p-4 rounded-xl border text-xs ${
              validationResult.valid
                ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                : 'bg-rose-50 border-rose-200 text-rose-900'
            }`}
          >
            <div className="flex items-start gap-3">
              {validationResult.valid ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              )}

              <div className="space-y-1">
                <p className="font-bold">
                  {validationResult.valid
                    ? 'Tài liệu PDF hợp lệ và đạt tiêu chuẩn nộp bài'
                    : 'Tài liệu không đạt chuẩn kiểm tra tự động'}
                </p>

                {validationResult.valid ? (
                  <p className="text-emerald-700 text-[11px] leading-relaxed">
                    Xác thực text-layer: <strong>Native ({validationResult.textDensity}%)</strong> • Số trang ước tính:{' '}
                    <strong>{validationResult.pageCount} trang</strong>. Sẵn sàng gửi tới hàng đợi phân tích Celery.
                  </p>
                ) : (
                  <p className="text-rose-700 text-[11px] leading-relaxed">
                    {validationResult.errorMsg}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Upload progress */}
        {isSubmitting && (
          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between text-slate-600 font-medium">
              <span>Đang tải lên máy chủ và kích hoạt worker Celery...</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-sky-600 transition-all duration-200"
                style={{ width: `${uploadProgress}%` }}
              ></div>
            </div>
          </div>
        )}

        {/* Action button */}
        <div className="pt-2 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onBack}
            className="px-4 py-2 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            Hủy
          </button>
          <button
            type="button"
            disabled={!validationResult?.valid || isSubmitting}
            onClick={handleConfirmSubmit}
            className="px-5 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 disabled:opacity-40 transition-colors shadow-2xs"
          >
            Xác nhận nộp bài
          </button>
        </div>
      </div>
    </div>
  );
};
