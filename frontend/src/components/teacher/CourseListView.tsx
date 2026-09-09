import React, { useState } from 'react';
import {
  Plus,
  BookOpen,
  ChevronRight,
  Search,
  Filter,
  Copy,
  Check,
  Download,
  Users,
  FileText,
  AlertCircle,
  CheckCircle2,
  SlidersHorizontal,
  LayoutGrid,
  List,
  Sparkles,
  Award,
  ArrowUpRight,
  ExternalLink,
  ShieldAlert,
} from 'lucide-react';
import { Course } from '../../types/docgrading';

interface CourseListViewProps {
  courses: Course[];
  onSelectCourse: (course: Course) => void;
  onCreateCourse: (course: Partial<Course>) => void;
  onGoToQueue?: (course: Course) => void;
}

export const CourseListView: React.FC<CourseListViewProps> = ({
  courses,
  onSelectCourse,
  onCreateCourse,
  onGoToQueue,
}) => {
  // State
  const [searchQuery, setSearchQuery] = useState('');
  const [semesterFilter, setSemesterFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'needs_review' | 'active' | 'archived'>('all');
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [rubricPreviewCourse, setRubricPreviewCourse] = useState<Course | null>(null);

  // Modal Create Course State
  const [showModal, setShowModal] = useState(false);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [semester, setSemester] = useState('Semester 2 · 2024');
  const [department, setDepartment] = useState('Bộ môn Kỹ thuật Phần mềm');
  const [credits, setCredits] = useState<number>(3);
  const [rubricStandard, setRubricStandard] = useState('IEEE-830 Software Requirements (SRS)');
  const [inviteCode, setInviteCode] = useState('');

  // Toast Helper
  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 2500);
  };

  const handleCopyInvite = (c: Course, e: React.MouseEvent) => {
    e.stopPropagation();
    const codeToCopy = c.inviteCode || c.code;
    navigator.clipboard?.writeText(codeToCopy);
    setCopiedId(c.id);
    showToast(`Đã sao chép mã mời lớp: ${codeToCopy}`);
    setTimeout(() => setCopiedId(null), 1800);
  };

  const handleExportGrades = (c: Course, e: React.MouseEvent) => {
    e.stopPropagation();
    showToast(`Đang kết xuất bảng điểm lớp ${c.code} theo Rubric (${c.studentCount} SV)...`);
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!code || !name) return;
    onCreateCourse({
      code: code.trim(),
      name: name.trim(),
      semester,
      department,
      credits: Number(credits) || 3,
      rubricStandard,
      inviteCode: inviteCode.trim() || `${code.replace(/[^A-Z0-9]/gi, '')}-2026`,
      studentCount: 0,
      assignmentCount: 0,
      activeAssignments: 0,
      pendingReviews: 0,
      gradedCount: 0,
      status: 'active',
    });
    setCode('');
    setName('');
    setInviteCode('');
    setShowModal(false);
    showToast(`Đã tạo thành công lớp môn học ${code}!`);
  };

  // Unique semesters for filter dropdown
  const semesters = Array.from(new Set(courses.map((c) => c.semester)));

  // Filter Logic
  const filteredCourses = courses.filter((c) => {
    const matchesSearch =
      c.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (c.department && c.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (c.inviteCode && c.inviteCode.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesSemester = semesterFilter === 'all' || c.semester === semesterFilter;

    let matchesStatus = true;
    if (statusFilter === 'needs_review') {
      matchesStatus = c.pendingReviews > 0;
    } else if (statusFilter === 'active') {
      matchesStatus = c.status !== 'archived';
    } else if (statusFilter === 'archived') {
      matchesStatus = c.status === 'archived';
    }

    return matchesSearch && matchesSemester && matchesStatus;
  });

  // KPI Calculations
  const totalCourses = courses.length;
  const totalStudents = courses.reduce((acc, c) => acc + c.studentCount, 0);
  const totalPendingReviews = courses.reduce((acc, c) => acc + c.pendingReviews, 0);
  const totalGraded = courses.reduce((acc, c) => acc + (c.gradedCount || 0), 0);
  const overallProgress = totalStudents > 0 ? Math.round((totalGraded / totalStudents) * 100) : 0;

  return (
    <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6 animate-fadeIn">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#172033] text-white px-4 py-2.5 rounded-xl shadow-[0_4px_16px_rgba(16,24,40,0.16)] border border-[#DDE2E8] text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-[#237A57] shrink-0" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header matching enterprise SaaS standard */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-[#172033] tracking-tight">Courses</h1>
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0] font-semibold">
              {courses.length} lớp học phần
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[#596579] mt-1">
            Organize assignments, rubrics and submissions by course.
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-[#1F4B7A] hover:bg-[#183C63] text-white rounded-lg text-xs font-semibold transition-colors shadow-2xs cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)]"
          >
            <Plus className="w-4 h-4 stroke-[2.5]" />
            <span>Create course</span>
          </button>
        </div>
      </div>

      {/* Teacher KPI Quick Metrics Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        <div className="bg-white rounded-xl border border-[#DDE2E8] hover:border-[#CBD5E1] p-3.5 flex items-center justify-between shadow-2xs transition-all">
          <div>
            <span className="text-[11px] font-semibold text-[#8893A5] uppercase tracking-wider block">
              Lớp phụ trách
            </span>
            <span className="text-2xl font-bold text-[#172033] mt-0.5 block tracking-tight">{totalCourses}</span>
            <span className="text-[11px] text-[#596579] mt-0.5 block">
              {courses.filter((c) => c.status !== 'archived').length} đang hoạt động
            </span>
          </div>
          <div className="w-9 h-9 rounded-lg bg-[#F3F5F7] border border-[#DDE2E8] flex items-center justify-center text-[#1F4B7A]">
            <BookOpen className="w-4 h-4 stroke-[2]" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-[#DDE2E8] hover:border-[#CBD5E1] p-3.5 flex items-center justify-between shadow-2xs transition-all">
          <div>
            <span className="text-[11px] font-semibold text-[#8893A5] uppercase tracking-wider block">
              Tổng số sinh viên
            </span>
            <span className="text-2xl font-bold text-[#172033] mt-0.5 block tracking-tight">{totalStudents}</span>
            <span className="text-[11px] text-[#596579] mt-0.5 block">Đã ghi danh lớp</span>
          </div>
          <div className="w-9 h-9 rounded-lg bg-[#EAF1F8] border border-[#D3E2F0] flex items-center justify-center text-[#1F4B7A]">
            <Users className="w-4 h-4 stroke-[2]" />
          </div>
        </div>

        <div
          onClick={() => setStatusFilter('needs_review')}
          className={`bg-white rounded-xl border p-3.5 flex items-center justify-between shadow-2xs cursor-pointer transition-all ${
            statusFilter === 'needs_review'
              ? 'border-[#A65F13] ring-1 ring-[#A65F13]'
              : 'border-[#DDE2E8] hover:border-[#CBD5E1]'
          }`}
        >
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-semibold text-[#8893A5] uppercase tracking-wider block">
                Cần duyệt ngay
              </span>
              {totalPendingReviews > 0 && (
                <span className="w-2 h-2 rounded-full bg-[#A65F13]"></span>
              )}
            </div>
            <span className="text-2xl font-bold text-[#A65F13] mt-0.5 block tracking-tight">
              {totalPendingReviews} <span className="text-xs font-normal text-[#596579]">bài nộp</span>
            </span>
            <span className="text-[11px] text-[#A65F13] mt-0.5 block font-medium">
              Chờ GV xác nhận điểm
            </span>
          </div>
          <div className="w-9 h-9 rounded-lg bg-[#FFF4E5] border border-[#F6E1C5] flex items-center justify-center text-[#A65F13]">
            <AlertCircle className="w-4 h-4 stroke-[2]" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-[#DDE2E8] hover:border-[#CBD5E1] p-3.5 flex items-center justify-between shadow-2xs transition-all">
          <div>
            <span className="text-[11px] font-semibold text-[#8893A5] uppercase tracking-wider block">
              Tiến độ chấm điểm
            </span>
            <span className="text-2xl font-bold text-[#172033] mt-0.5 block tracking-tight">
              {overallProgress}%
            </span>
            <span className="text-[11px] text-[#237A57] font-medium mt-0.5 block">
              {totalGraded}/{totalStudents} SV đã có điểm
            </span>
          </div>
          <div className="w-9 h-9 rounded-lg bg-[#EAF6F0] border border-[#CCE8D9] flex items-center justify-center text-[#237A57]">
            <CheckCircle2 className="w-4 h-4 stroke-[2]" />
          </div>
        </div>
      </div>

      {/* Search, Filter Bar & View Mode Toggle */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-white p-2.5 rounded-xl border border-[#DDE2E8] shadow-2xs">
        <div className="flex flex-1 items-center gap-2">
          {/* Search box */}
          <div className="relative flex-1 max-w-sm">
            <Search className="w-3.5 h-3.5 text-[#8893A5] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Tìm theo mã lớp, tên môn học, bộ môn..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 bg-[#F3F5F7] hover:bg-[#E9EDF2] focus:bg-white border border-[#DDE2E8] rounded-lg text-xs text-[#172033] placeholder:text-[#8893A5] focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] transition-all"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#8893A5] hover:text-[#172033] text-xs cursor-pointer"
              >
                ✕
              </button>
            )}
          </div>

          {/* Semester Filter */}
          <div className="flex items-center gap-1.5">
            <select
              value={semesterFilter}
              onChange={(e) => setSemesterFilter(e.target.value)}
              className="px-2.5 py-1.5 bg-[#F3F5F7] border border-[#DDE2E8] hover:border-[#CBD5E1] rounded-lg text-xs text-[#172033] focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] cursor-pointer font-medium transition-colors"
            >
              <option value="all">Tất cả học kỳ</option>
              {semesters.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Status Pills & View Mode Switcher */}
        <div className="flex items-center justify-between sm:justify-end gap-2 border-t md:border-t-0 pt-2 md:pt-0 border-[#E9EDF2]">
          <div className="flex items-center gap-1 bg-[#F3F5F7] p-0.5 rounded-lg border border-[#E9EDF2] text-xs">
            <button
              type="button"
              onClick={() => setStatusFilter('all')}
              className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                statusFilter === 'all'
                  ? 'bg-white font-semibold text-[#172033] shadow-2xs border border-[#DDE2E8]'
                  : 'text-[#596579] hover:text-[#172033]'
              }`}
            >
              Tất cả
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('needs_review')}
              className={`px-2.5 py-1 rounded-md transition-colors flex items-center gap-1 cursor-pointer ${
                statusFilter === 'needs_review'
                  ? 'bg-white font-semibold text-[#A65F13] shadow-2xs border border-[#F6E1C5]'
                  : 'text-[#596579] hover:text-[#172033]'
              }`}
            >
              <span>Cần duyệt</span>
              {totalPendingReviews > 0 && (
                <span className="w-4 h-4 rounded-full bg-[#FFF4E5] text-[#A65F13] border border-[#F6E1C5] text-[10px] font-bold flex items-center justify-center">
                  {totalPendingReviews}
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter('active')}
              className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                statusFilter === 'active'
                  ? 'bg-white font-semibold text-[#172033] shadow-2xs border border-[#DDE2E8]'
                  : 'text-[#596579] hover:text-[#172033]'
              }`}
            >
              Đang dạy
            </button>
          </div>

          <div className="flex items-center border-l border-[#DDE2E8] pl-2 gap-1">
            <button
              type="button"
              onClick={() => setViewMode('grid')}
              title="Chế độ xem thẻ (Grid)"
              className={`p-1.5 rounded-md transition-colors cursor-pointer ${
                viewMode === 'grid'
                  ? 'bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0]'
                  : 'text-[#8893A5] hover:text-[#172033] hover:bg-[#F3F5F7]'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setViewMode('table')}
              title="Chế độ xem bảng (Table)"
              className={`p-1.5 rounded-md transition-colors cursor-pointer ${
                viewMode === 'table'
                  ? 'bg-[#EAF1F8] text-[#1F4B7A] border border-[#D3E2F0]'
                  : 'text-[#8893A5] hover:text-[#172033] hover:bg-[#F3F5F7]'
              }`}
            >
              <List className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Content: Grid Mode or Table Mode */}
      {filteredCourses.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#DDE2E8] p-12 text-center max-w-md mx-auto space-y-3 shadow-2xs">
          <div className="w-12 h-12 rounded-full bg-[#F3F5F7] border border-[#DDE2E8] flex items-center justify-center mx-auto text-[#8893A5]">
            <Search className="w-6 h-6" />
          </div>
          <h3 className="font-bold text-[#172033] text-sm">Không tìm thấy lớp học phần phù hợp</h3>
          <p className="text-xs text-[#596579]">
            Hãy thử thay đổi từ khóa tìm kiếm hoặc đặt lại các bộ lọc học kỳ.
          </p>
          <button
            type="button"
            onClick={() => {
              setSearchQuery('');
              setSemesterFilter('all');
              setStatusFilter('all');
            }}
            className="px-3.5 py-1.5 rounded-lg bg-[#F3F5F7] hover:bg-[#E9EDF2] border border-[#DDE2E8] text-[#172033] text-xs font-semibold transition-colors cursor-pointer"
          >
            Đặt lại bộ lọc
          </button>
        </div>
      ) : viewMode === 'grid' ? (
        /* GRID VIEW - Enhanced for Lecturers */
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 max-w-5xl">
          {filteredCourses.map((c) => {
            const gradedRatio =
              c.studentCount > 0
                ? Math.round(((c.gradedCount ?? (c.studentCount - c.pendingReviews)) / c.studentCount) * 100)
                : 0;
            const gradedCount = c.gradedCount ?? Math.max(0, c.studentCount - c.pendingReviews);

            return (
              <div
                key={c.id}
                onClick={() => onSelectCourse(c)}
                className="bg-white rounded-xl border border-[#DDE2E8] hover:border-[#B4C6D8] shadow-2xs hover:shadow-[0_4px_20px_rgba(31,75,122,0.08)] transition-all p-5 flex flex-col justify-between group cursor-pointer"
              >
                {/* Phần thông tin chính */}
                <div className="space-y-3">
                  {/* Dòng tiêu đề và trạng thái */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-xs text-[#596579]">
                        <span className="font-mono font-semibold text-[#1F4B7A] bg-[#EAF1F8] px-2 py-0.5 rounded text-[11px]">
                          {c.code}
                        </span>
                        {c.credits && <span>· {c.credits} tín chỉ</span>}
                        <span className="truncate">· {c.semester}</span>
                      </div>
                      <h2 className="text-base font-bold text-[#172033] mt-1.5 group-hover:text-[#1F4B7A] transition-colors leading-snug">
                        {c.name}
                      </h2>
                      {c.department && (
                        <p className="text-xs text-[#8893A5] mt-0.5">{c.department}</p>
                      )}
                    </div>

                    {/* Huy hiệu trạng thái duy nhất ở góc trên */}
                    {c.pendingReviews > 0 ? (
                      <span className="shrink-0 text-xs font-semibold px-2.5 py-1 rounded-full bg-[#FFF4E5] text-[#A65F13] border border-[#F6E1C5]">
                        {c.pendingReviews} cần duyệt
                      </span>
                    ) : (
                      <span className="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full bg-[#F3F5F7] text-[#596579]">
                        {c.activeAssignments > 0 ? `${c.activeAssignments} bài mở` : 'Đã chấm xong'}
                      </span>
                    )}
                  </div>

                  {/* Thông tin phụ trợ: Rubric & Mã mời */}
                  <div className="flex items-center justify-between gap-2 pt-1 text-xs text-[#596579]">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRubricPreviewCourse(c);
                      }}
                      className="text-xs text-[#596579] hover:text-[#1F4B7A] hover:underline truncate max-w-[250px] text-left cursor-pointer"
                      title="Xem bộ tiêu chí Rubric áp dụng"
                    >
                      Rubric: {c.rubricStandard || 'IEEE-830 SRS'}
                    </button>

                    <button
                      type="button"
                      onClick={(e) => handleCopyInvite(c, e)}
                      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-[#F3F5F7] hover:bg-[#E9EDF2] text-[#172033] text-xs font-mono transition-colors shrink-0 cursor-pointer"
                      title="Sao chép mã mời"
                    >
                      <span className="text-[#8893A5] font-sans text-[11px]">Mã:</span>
                      <span className="font-semibold">{c.inviteCode || c.code}</span>
                      {copiedId === c.id ? (
                        <Check className="w-3 h-3 text-[#237A57]" />
                      ) : (
                        <Copy className="w-3 h-3 text-[#8893A5]" />
                      )}
                    </button>
                  </div>

                  {/* Tiến độ chấm điểm tích hợp */}
                  <div className="pt-1 space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[#596579]">
                        Tiến độ chấm ({c.studentCount > 0 ? `${gradedCount}/${c.studentCount} SV` : '0 SV'})
                      </span>
                      <span className="font-semibold text-[#172033]">{gradedRatio}%</span>
                    </div>
                    <div className="w-full h-1.5 bg-[#E9EDF2] rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${
                          gradedRatio >= 100 ? 'bg-[#237A57]' : 'bg-[#1F4B7A]'
                        }`}
                        style={{ width: `${gradedRatio}%` }}
                      ></div>
                    </div>
                  </div>
                </div>

                {/* Chân thẻ: Thống kê số lượng bên trái, Nút Vào lớp duy nhất bên phải */}
                <div className="mt-5 pt-3 border-t border-[#E9EDF2] flex items-center justify-between text-xs">
                  <div className="text-[#596579]">
                    <span className="font-semibold text-[#172033]">{c.studentCount}</span> sinh viên ·{' '}
                    <span className="font-semibold text-[#172033]">{c.assignmentCount}</span> bài tập
                  </div>

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectCourse(c);
                    }}
                    className="px-3.5 py-1.5 rounded-lg bg-[#1F4B7A] hover:bg-[#183C63] text-white font-semibold transition-colors shadow-2xs cursor-pointer"
                  >
                    Vào lớp
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* TABLE VIEW - Compact for Lecturers with Many Classes */
        <div className="bg-white rounded-xl border border-[#DDE2E8] overflow-hidden shadow-2xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F3F5F7] border-b border-[#DDE2E8] text-[#8893A5] font-semibold text-[11px] uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">Mã & Tên lớp môn học</th>
                  <th className="py-3 px-3">Học kỳ / Khoa</th>
                  <th className="py-3 px-3">Rubric chuẩn</th>
                  <th className="py-3 px-3 text-center">Sinh viên</th>
                  <th className="py-3 px-3 text-center">Đợt nộp</th>
                  <th className="py-3 px-3 text-center">Chờ duyệt</th>
                  <th className="py-3 px-3">Tiến độ</th>
                  <th className="py-3 px-4 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E9EDF2]">
                {filteredCourses.map((c) => {
                  const gradedRatio =
                    c.studentCount > 0
                      ? Math.round(((c.gradedCount ?? (c.studentCount - c.pendingReviews)) / c.studentCount) * 100)
                      : 0;

                  return (
                    <tr
                      key={c.id}
                      onClick={() => onSelectCourse(c)}
                      className="hover:bg-[#F7F8FA] transition-colors cursor-pointer group"
                    >
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-lg bg-[#F3F5F7] border border-[#DDE2E8] flex items-center justify-center text-[#1F4B7A] shrink-0">
                            <BookOpen className="w-4 h-4" />
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono font-bold text-[#1F4B7A] bg-[#EAF1F8] px-1.5 py-0.5 rounded border border-[#D3E2F0] text-[11px]">
                                {c.code}
                              </span>
                              {c.activeAssignments > 0 && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#EAF6F0] text-[#237A57] border border-[#CCE8D9] font-medium">
                                  {c.activeAssignments} open
                                </span>
                              )}
                            </div>
                            <span className="text-[#172033] font-medium group-hover:text-[#1F4B7A] block mt-0.5 transition-colors">
                              {c.name}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="py-3.5 px-3">
                        <span className="text-[#172033] block font-medium">{c.semester}</span>
                        <span className="text-[11px] text-[#8893A5] block">{c.department || 'Bộ môn KTPM'}</span>
                      </td>
                      <td className="py-3.5 px-3">
                        <span className="text-[#596579] block truncate max-w-[160px]" title={c.rubricStandard}>
                          {c.rubricStandard || 'IEEE-830 SRS'}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => handleCopyInvite(c, e)}
                          className="text-[10px] text-[#8893A5] hover:text-[#1F4B7A] inline-flex items-center gap-1 mt-0.5 cursor-pointer"
                        >
                          <span>Mã: {c.inviteCode || c.code}</span>
                          <Copy className="w-2.5 h-2.5" />
                        </button>
                      </td>
                      <td className="py-3.5 px-3 text-center font-semibold text-[#172033]">
                        {c.studentCount}
                      </td>
                      <td className="py-3.5 px-3 text-center font-semibold text-[#172033]">
                        {c.assignmentCount}
                      </td>
                      <td className="py-3.5 px-3 text-center">
                        {c.pendingReviews > 0 ? (
                          <span className="inline-block px-2 py-0.5 rounded-md bg-[#FFF4E5] text-[#A65F13] border border-[#F6E1C5] font-bold text-[11px]">
                            {c.pendingReviews}
                          </span>
                        ) : (
                          <span className="text-[#8893A5]">0</span>
                        )}
                      </td>
                      <td className="py-3.5 px-3">
                        <div className="w-24 space-y-1">
                          <div className="flex items-center justify-between text-[10px] text-[#596579]">
                            <span>{gradedRatio}%</span>
                          </div>
                          <div className="w-full h-1.5 bg-[#E9EDF2] rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                gradedRatio >= 100 ? 'bg-[#237A57]' : 'bg-[#1F4B7A]'
                              }`}
                              style={{ width: `${gradedRatio}%` }}
                            ></div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 text-right">
                        <div className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                          {c.pendingReviews > 0 && (
                            <button
                              type="button"
                              onClick={() => (onGoToQueue ? onGoToQueue(c) : onSelectCourse(c))}
                              className="px-2 py-1 rounded-lg bg-[#FFF4E5] hover:bg-[#FFECCF] text-[#A65F13] text-[11px] font-semibold border border-[#F6E1C5] transition-colors cursor-pointer"
                            >
                              Duyệt bài
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => onSelectCourse(c)}
                            className="px-2.5 py-1 rounded-lg bg-[#1F4B7A] hover:bg-[#183C63] text-white text-[11px] font-semibold transition-colors cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)]"
                          >
                            Vào lớp
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modal: Create new course (Designed for Lecturers) */}
      {showModal && (
        <div className="fixed inset-0 bg-[#172033]/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-[0_16px_36px_rgba(16,24,40,0.16)] border border-[#DDE2E8] w-full max-w-lg p-6 space-y-4 animate-scaleUp">
            <div className="flex items-center justify-between border-b border-[#E9EDF2] pb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#1F4B7A] text-white flex items-center justify-center">
                  <BookOpen className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h3 className="font-bold text-[#172033] text-sm">Tạo lớp học phần mới</h3>
                  <p className="text-[11px] text-[#596579]">Thiết lập thông tin môn học và chuẩn Rubric đánh giá</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="text-[#8893A5] hover:text-[#172033] text-sm p-1 rounded-md transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-3.5 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#172033] font-semibold mb-1">Mã học phần / Lớp (*)</label>
                  <input
                    type="text"
                    required
                    placeholder="VD: INT2208-02 hoặc CS4999"
                    value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                    className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] font-mono text-xs text-[#172033] transition-all"
                  />
                </div>
                <div>
                  <label className="block text-[#172033] font-semibold mb-1">Số tín chỉ</label>
                  <input
                    type="number"
                    min={1}
                    max={15}
                    value={credits}
                    onChange={(e) => setCredits(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] text-xs text-[#172033] transition-all"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#172033] font-semibold mb-1">Tên môn học (*)</label>
                <input
                  type="text"
                  required
                  placeholder="VD: Công nghệ phần mềm, Đồ án tốt nghiệp..."
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] text-xs text-[#172033] transition-all"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#172033] font-semibold mb-1">Học kỳ</label>
                  <select
                    value={semester}
                    onChange={(e) => setSemester(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] text-xs text-[#172033] font-medium transition-all cursor-pointer"
                  >
                    <option value="Semester 2 · 2024">Semester 2 · 2024</option>
                    <option value="Academic year 2024">Academic year 2024</option>
                    <option value="Summer · 2024">Summer · 2024</option>
                    <option value="Semester 1 · 2025">Semester 1 · 2025</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[#172033] font-semibold mb-1">Khoa / Bộ môn công tác</label>
                  <input
                    type="text"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] text-xs text-[#172033] transition-all"
                  />
                </div>
              </div>

              {/* Rubric Standard Selection */}
              <div>
                <label className="block text-[#172033] font-semibold mb-1 flex items-center justify-between">
                  <span>Bộ tiêu chí Rubric áp dụng</span>
                  <span className="text-[10px] text-[#8893A5] font-normal">Có thể tùy chỉnh sau</span>
                </label>
                <select
                  value={rubricStandard}
                  onChange={(e) => setRubricStandard(e.target.value)}
                  className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] text-xs text-[#172033] font-medium transition-all cursor-pointer"
                >
                  <option value="IEEE-830 Software Requirements (SRS)">
                    Đặc tả yêu cầu phần mềm chuẩn IEEE-830 (SRS 3 phần)
                  </option>
                  <option value="Đồ án Khóa luận tốt nghiệp Đại học">
                    Đồ án Khóa luận tốt nghiệp Đại học (Báo cáo tổng kết 5 chương)
                  </option>
                  <option value="Báo cáo Thực tập Doanh nghiệp & Nhật ký">
                    Báo cáo Thực tập Doanh nghiệp & Nhật ký công tác
                  </option>
                  <option value="Tài liệu Kiến trúc Phần mềm (SAD IEEE 1471)">
                    Tài liệu Kiến trúc Phần mềm (SAD IEEE 1471 / 4+1 View)
                  </option>
                </select>
              </div>

              <div>
                <label className="block text-[#172033] font-semibold mb-1">
                  Mã mời lớp (Course Invite Code)
                </label>
                <input
                  type="text"
                  placeholder="Để trống để hệ thống tự tạo (vd: SRS-2026)"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                  className="w-full px-3 py-2 bg-[#F3F5F7] focus:bg-white border border-[#DDE2E8] rounded-lg focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)] focus:border-[#1F4B7A] font-mono text-xs text-[#172033] transition-all"
                />
                <p className="text-[10px] text-[#8893A5] mt-1">
                  Sinh viên sẽ nhập mã này khi đăng ký hoặc tham gia lớp để tự động ghi danh.
                </p>
              </div>

              <div className="pt-3 border-t border-[#E9EDF2] flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3.5 py-2 rounded-lg border border-[#DDE2E8] text-[#596579] hover:bg-[#F3F5F7] font-semibold transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-[#1F4B7A] text-white font-semibold hover:bg-[#183C63] transition-colors shadow-2xs cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)]"
                >
                  Tạo lớp học phần
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Preview Rubric Standard */}
      {rubricPreviewCourse && (
        <div className="fixed inset-0 bg-[#172033]/40 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-[0_16px_36px_rgba(16,24,40,0.16)] border border-[#DDE2E8] w-full max-w-lg p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-[#E9EDF2] pb-3">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#EAF1F8] border border-[#D3E2F0] flex items-center justify-center text-[#1F4B7A]">
                  <Sparkles className="w-3.5 h-3.5" />
                </div>
                <div>
                  <h3 className="font-bold text-[#172033] text-sm">
                    Tiêu chuẩn Rubric: {rubricPreviewCourse.code}
                  </h3>
                  <p className="text-[11px] text-[#596579]">{rubricPreviewCourse.name}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setRubricPreviewCourse(null)}
                className="text-[#8893A5] hover:text-[#172033] text-sm p-1 rounded-md transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="p-3 bg-[#F3F5F7] rounded-xl border border-[#DDE2E8] space-y-1">
                <span className="font-semibold text-[#172033] block">
                  {rubricPreviewCourse.rubricStandard || 'IEEE-830 Software Requirements (SRS)'}
                </span>
                <p className="text-[#596579] text-[11px] leading-relaxed">
                  Bộ tiêu chí chuẩn hóa tự động kiểm tra cú pháp, bảng biểu, danh mục Use Case, phi chức năng và phát hiện đoạn trích dẫn thiếu minh chứng.
                </p>
              </div>

              <div className="space-y-2">
                <span className="font-semibold text-[#172033] text-[11px] block">
                  Trọng số & Tiêu chí chính:
                </span>
                <div className="divide-y divide-[#E9EDF2] border border-[#DDE2E8] rounded-xl overflow-hidden">
                  <div className="p-2.5 flex items-center justify-between bg-white">
                    <span className="font-medium text-[#172033]">Cấu trúc 3 phần IEEE 830</span>
                    <span className="font-mono font-bold text-[#1F4B7A] bg-[#EAF1F8] px-2 py-0.5 rounded border border-[#D3E2F0]">2.0 điểm (20%)</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between bg-white">
                    <span className="font-medium text-[#172033]">Đặc tả Use Case & Luồng sự kiện</span>
                    <span className="font-mono font-bold text-[#1F4B7A] bg-[#EAF1F8] px-2 py-0.5 rounded border border-[#D3E2F0]">3.5 điểm (35%)</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between bg-white">
                    <span className="font-medium text-[#172033]">Yêu cầu phi chức năng (NFR & MoSCoW)</span>
                    <span className="font-mono font-bold text-[#1F4B7A] bg-[#EAF1F8] px-2 py-0.5 rounded border border-[#D3E2F0]">2.5 điểm (25%)</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between bg-white">
                    <span className="font-medium text-[#172033]">Ma trận truy vết & Định dạng chuẩn</span>
                    <span className="font-mono font-bold text-[#1F4B7A] bg-[#EAF1F8] px-2 py-0.5 rounded border border-[#D3E2F0]">2.0 điểm (20%)</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-3 border-t border-[#E9EDF2] flex items-center justify-between">
              <button
                type="button"
                onClick={() => {
                  const c = rubricPreviewCourse;
                  setRubricPreviewCourse(null);
                  onSelectCourse(c);
                }}
                className="text-[#1F4B7A] hover:text-[#183C63] font-semibold text-xs inline-flex items-center gap-1 transition-colors cursor-pointer"
              >
                <span>Chỉnh sửa tiêu chí trong Workspace</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setRubricPreviewCourse(null)}
                className="px-3.5 py-1.5 rounded-lg bg-[#1F4B7A] text-white font-semibold text-xs hover:bg-[#183C63] transition-colors shadow-2xs cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-[rgba(31,75,122,0.18)]"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
