import React from 'react';
import {
  FolderKanban,
  Plus,
  ArrowLeft,
  Calendar,
  FileText,
  CheckCircle2,
  Clock,
  Eye,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { Course, Assignment } from '../../types/docgrading';

interface CourseWorkspaceViewProps {
  course: Course;
  assignments: Assignment[];
  onBack: () => void;
  onOpenCreateWizard: () => void;
  onOpenQueue: (assignment: Assignment) => void;
  onEditAssignment: (assignment: Assignment) => void;
}

export const CourseWorkspaceView: React.FC<CourseWorkspaceViewProps> = ({
  course,
  assignments,
  onBack,
  onOpenCreateWizard,
  onOpenQueue,
  onEditAssignment,
}) => {
  const filteredAssignments = assignments.filter((a) => a.courseId === course.id);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Top breadcrumb & back */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1 hover:text-slate-900 font-medium"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Danh sách môn học</span>
        </button>
        <span>/</span>
        <span className="font-mono text-slate-700">{course.code}</span>
      </div>

      {/* Course Hero Card */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-2xs">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-md bg-sky-50 text-sky-700 border border-sky-200/80 font-mono text-xs font-bold">
                {course.code}
              </span>
              <span className="text-xs text-slate-500">{course.semester}</span>
            </div>
            <h1 className="text-lg font-bold text-slate-900 mt-1.5">{course.name}</h1>
            <p className="text-xs text-slate-500 mt-1">
              Bộ môn Kỹ thuật Phần mềm • Sinh viên: {course.studentCount} • Số đợt nộp: {filteredAssignments.length}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onOpenCreateWizard}
              className="inline-flex items-center gap-2 px-3.5 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800 transition-colors shadow-2xs"
            >
              <Plus className="w-4 h-4" />
              <span>Tạo đợt nộp bài mới</span>
            </button>
          </div>
        </div>
      </div>

      {/* Assignments Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
            Các đợt nộp bài tập & Báo cáo SRS ({filteredAssignments.length})
          </h2>
        </div>

        {filteredAssignments.length === 0 ? (
          <div className="bg-white rounded-xl border border-dashed border-slate-300 p-8 text-center space-y-3">
            <FileText className="w-10 h-10 text-slate-400 mx-auto" />
            <p className="text-sm font-medium text-slate-700">Chưa có đợt nộp nào trong môn học này</p>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              Tạo đợt nộp báo cáo để sinh viên nộp file PDF và kích hoạt hệ thống phân tích rubric tự động.
            </p>
            <button
              type="button"
              onClick={onOpenCreateWizard}
              className="px-3.5 py-2 bg-slate-900 text-white rounded-lg text-xs font-medium hover:bg-slate-800"
            >
              Tạo đợt nộp đầu tiên
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {filteredAssignments.map((a) => {
              const statusBadge =
                a.status === 'open'
                  ? { text: 'Đang mở nộp', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
                  : a.status === 'draft'
                  ? { text: 'Bản nháp (Draft)', color: 'bg-slate-100 text-slate-600 border-slate-200' }
                  : { text: 'Đã đóng', color: 'bg-rose-50 text-rose-700 border-rose-200' };

              return (
                <div
                  key={a.id}
                  className="bg-white rounded-xl border border-slate-200 p-5 hover:border-slate-300 transition-all shadow-2xs flex flex-col md:flex-row md:items-center justify-between gap-4"
                >
                  <div className="space-y-2 max-w-2xl">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 text-[11px] font-semibold rounded-md border ${statusBadge.color}`}>
                        {statusBadge.text}
                      </span>
                      <span className="text-xs text-slate-400 flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        Hạn chót: {new Date(a.dueDate).toLocaleDateString('vi-VN')} {new Date(a.dueDate).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>

                    <h3 className="text-sm font-bold text-slate-900">{a.title}</h3>
                    <p className="text-xs text-slate-500 line-clamp-2 leading-relaxed">{a.description}</p>

                    <div className="flex items-center gap-4 text-xs text-slate-500 pt-1">
                      <span className="flex items-center gap-1">
                        <ShieldCheck className="w-3.5 h-3.5 text-sky-600" />
                        Rubric: 12 tiêu chí chuẩn IEEE 830 (100%)
                      </span>
                      <span>•</span>
                      <span>Định dạng: Chỉ nhận PDF có text layer</span>
                    </div>
                  </div>

                  <div className="flex flex-col sm:flex-row md:flex-col lg:flex-row items-stretch md:items-end lg:items-center gap-3 shrink-0 pt-3 md:pt-0 border-t md:border-t-0 border-slate-100">
                    {/* Metrics counts */}
                    <div className="grid grid-cols-3 gap-2 text-center text-xs bg-slate-50 p-2 rounded-lg border border-slate-100">
                      <div className="px-2">
                        <span className="text-[10px] text-slate-400 block">Đã nộp</span>
                        <span className="font-bold text-slate-800">{a.submittedCount}</span>
                      </div>
                      <div className="px-2 border-x border-slate-200">
                        <span className="text-[10px] text-slate-400 block">Đã duyệt</span>
                        <span className="font-bold text-slate-800">{a.reviewedCount}</span>
                      </div>
                      <div className="px-2">
                        <span className="text-[10px] text-slate-400 block">Công bố</span>
                        <span className="font-bold text-emerald-600">{a.publishedCount}</span>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => onOpenQueue(a)}
                        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 transition-colors shadow-2xs"
                      >
                        <Eye className="w-3.5 h-3.5" />
                        <span>Hàng đợi duyệt bài</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => onEditAssignment(a)}
                        className="p-2 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                        title="Chỉnh sửa cấu hình"
                      >
                        <Settings className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
