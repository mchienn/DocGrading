import { useState } from "react";
import {
  LayoutDashboard, Users, FileText, Bell, Search,
  ChevronRight, ChevronLeft, ChevronDown, Upload,
  CheckCircle, XCircle, AlertCircle, Clock, Filter,
  MoreHorizontal, Download, ZoomIn, ZoomOut,
  MessageSquare, Pencil, Check, X, ArrowRight,
  RotateCcw, Shield, Activity, Inbox,
  Star, Layers, BookOpen, AlertTriangle, RefreshCw,
  Plus, Minus, Settings, FileCheck,
  GraduationCap, BarChart2, ListTodo
} from "lucide-react";
import { clsx } from "clsx";

// ---- Types ----
type Role = "admin" | "teacher" | "student";
type View =
  | "admin-dashboard" | "admin-users" | "admin-jobs" | "admin-audit"
  | "teacher-courses" | "teacher-course" | "teacher-course-editor" | "teacher-assignment-editor" | "teacher-queue" | "teacher-review"
  | "student-assignments" | "student-upload" | "student-status" | "student-results";

type Status =
  | "received" | "checking" | "waiting" | "evaluating"
  | "needs-review" | "pending-approval" | "approved" | "published"
  | "error" | "resubmit";

// ---- Status Config ----
const STATUS: Record<Status, { label: string; cls: string; dot: string }> = {
  received:           { label: "Received",          cls: "bg-gray-100 text-gray-600",      dot: "bg-gray-400" },
  checking:           { label: "Checking PDF",      cls: "bg-sky-50 text-sky-700",         dot: "bg-sky-400" },
  waiting:            { label: "Queued",            cls: "bg-amber-50 text-amber-700",     dot: "bg-amber-400" },
  evaluating:         { label: "Evaluating",        cls: "bg-violet-50 text-violet-700",   dot: "bg-violet-400" },
  "needs-review":     { label: "Needs review",      cls: "bg-orange-50 text-orange-700",   dot: "bg-orange-400" },
  "pending-approval": { label: "Pending approval",  cls: "bg-blue-50 text-blue-700",       dot: "bg-blue-400" },
  approved:           { label: "Approved",          cls: "bg-green-50 text-green-700",     dot: "bg-green-500" },
  published:          { label: "Published",         cls: "bg-green-100 text-green-800",    dot: "bg-green-600" },
  error:              { label: "Processing failed", cls: "bg-red-50 text-red-700",         dot: "bg-red-500" },
  resubmit:           { label: "Resubmission needed", cls: "bg-red-50 text-red-700",        dot: "bg-red-400" },
};

function StatusBadge({ status }: { status: Status }) {
  const s = STATUS[status];
  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap", s.cls)}>
      <span className={clsx("size-1.5 rounded-full flex-shrink-0", s.dot)} />
      {s.label}
    </span>
  );
}

// ---- Mock Data ----
const SUBMISSIONS = [
  { id: "SUB-001", student: "Nguyễn Văn A", studentId: "20210001", assignment: "Software Requirements Specification", version: 1, status: "needs-review" as Status, submittedAt: "15/07 14:32", confidence: 0.87, suggestedScore: 7.4, reviewer: null, pages: 48 },
  { id: "SUB-002", student: "Trần Thị B",   studentId: "20210002", assignment: "Software Requirements Specification", version: 2, status: "pending-approval" as Status, submittedAt: "15/07 13:15", confidence: 0.92, suggestedScore: 8.1, reviewer: "Minh", pages: 62 },
  { id: "SUB-003", student: "Lê Văn C",     studentId: "20210003", assignment: "Software Requirements Specification", version: 1, status: "evaluating" as Status,  submittedAt: "15/07 12:00", confidence: null, suggestedScore: null, reviewer: null, pages: 35 },
  { id: "SUB-004", student: "Phạm Thị D",   studentId: "20210004", assignment: "Software Requirements Specification", version: 1, status: "error" as Status,         submittedAt: "15/07 11:30", confidence: null, suggestedScore: null, reviewer: null, pages: null },
  { id: "SUB-005", student: "Hoàng Văn E",  studentId: "20210005", assignment: "Software Requirements Specification", version: 1, status: "approved" as Status,      submittedAt: "14/07 16:45", confidence: 0.89, suggestedScore: 6.8, reviewer: "Hà", pages: 51 },
  { id: "SUB-006", student: "Vũ Thị F",     studentId: "20210006", assignment: "Software Requirements Specification", version: 3, status: "published" as Status,     submittedAt: "14/07 15:20", confidence: 0.95, suggestedScore: 9.2, reviewer: "Minh", pages: 78 },
];

const CRITERIA = [
  { id: "C1", name: "Document structure",  weight: 15, suggestedScore: 13, confidence: 0.91, status: "accepted" as const, findings: 0 },
  { id: "C2", name: "Requirements analysis", weight: 25, suggestedScore: 18, confidence: 0.85, status: "pending"  as const, findings: 2 },
  { id: "C3", name: "Use Case Diagram",   weight: 20, suggestedScore: 14, confidence: 0.78, status: "pending"  as const, findings: 1 },
  { id: "C4", name: "System design",      weight: 25, suggestedScore: 20, confidence: 0.93, status: "accepted" as const, findings: 1 },
  { id: "C5", name: "Consistency",        weight: 15, suggestedScore: 10, confidence: 0.72, status: "pending"  as const, findings: 2 },
];

const FINDINGS = [
  { id: "F1", criterionId: "C2", severity: "major"    as const, page: 12, description: "The use-case table is missing the Payment System actor.", suggestion: "Add the actor and the payment-related use cases." },
  { id: "F2", criterionId: "C2", severity: "minor"    as const, page: 18, description: "The alternative flow for UC-04 is incomplete.", suggestion: "Add at least two alternative scenarios for UC-04." },
  { id: "F3", criterionId: "C3", severity: "major"    as const, page: 23, description: "The Use Case Diagram has no system boundary.", suggestion: "Add a system boundary around all internal use cases." },
  { id: "F4", criterionId: "C4", severity: "minor"    as const, page: 35, description: "The inheritance relationship between two entity classes is not explained.", suggestion: "Describe the inheritance relationship in the class diagram." },
  { id: "F5", criterionId: "C5", severity: "critical" as const, page: 31, description: "The terms user and customer are used interchangeably throughout the document.", suggestion: "Use one term consistently or define the distinction." },
  { id: "F6", criterionId: "C5", severity: "minor"    as const, page: 44, description: "Database table names do not match the entity names in the ERD.", suggestion: "Align table names with the corresponding entities." },
];

type Course = {
  id: string;
  code: string;
  name: string;
  term: string;
  students: number;
};

type Assignment = {
  id: string;
  courseId: string;
  title: string;
  description: string;
  dueDate: string;
  attempts: number;
  status: "draft" | "open" | "closed";
  submitted: number;
  reviewed: number;
  published: number;
  rubric: string;
  requireAppendix: boolean;
  templateName: string;
};

const INITIAL_COURSES: Course[] = [
  { id: "COURSE-SE", code: "INT2208-01", name: "Công nghệ phần mềm", term: "Semester 2 · 2024", students: 42 },
  { id: "COURSE-THESIS", code: "CS4999", name: "Khóa luận tốt nghiệp", term: "Academic year 2024", students: 18 },
  { id: "COURSE-INTERNSHIP", code: "INT3501", name: "Thực tập doanh nghiệp", term: "Summer · 2024", students: 30 },
];

const INITIAL_ASSIGNMENTS: Assignment[] = [
  { id: "ASG-SRS", courseId: "COURSE-SE", title: "Software Requirements Specification", description: "Submit the final SRS report for automated analysis and lecturer review.", dueDate: "2024-07-31", attempts: 3, status: "open", submitted: 24, reviewed: 18, published: 12, rubric: "SRS Standard v2.1", requireAppendix: false, templateName: "SRS-template.docx" },
  { id: "ASG-DESIGN", courseId: "COURSE-SE", title: "System Design Report", description: "Architecture, data model, component and deployment design.", dueDate: "2024-08-18", attempts: 2, status: "draft", submitted: 0, reviewed: 0, published: 0, rubric: "Software Design v1.0", requireAppendix: true, templateName: "Design-report-template.docx" },
  { id: "ASG-THESIS", courseId: "COURSE-THESIS", title: "Final Thesis Report", description: "Final thesis manuscript and supporting appendix.", dueDate: "2024-08-15", attempts: 2, status: "open", submitted: 11, reviewed: 6, published: 4, rubric: "Thesis Template v1.0", requireAppendix: true, templateName: "Thesis-template.docx" },
  { id: "ASG-INTERNSHIP", courseId: "COURSE-INTERNSHIP", title: "Internship Report", description: "Describe the organization, assigned work and learning outcomes.", dueDate: "2024-08-20", attempts: 3, status: "closed", submitted: 30, reviewed: 30, published: 30, rubric: "Internship Report v3.0", requireAppendix: false, templateName: "Internship-report-template.docx" },
];

// ---- Sidebar ----
type NavItem = { icon: React.FC<{ className?: string }>; label: string; view: View };

const NAV: Record<Role, NavItem[]> = {
  admin:   [
    { icon: LayoutDashboard, label: "Dashboard",       view: "admin-dashboard" },
    { icon: Users,           label: "Users",           view: "admin-users" },
    { icon: Activity,        label: "Job Monitoring",  view: "admin-jobs" },
    { icon: Shield,          label: "Audit Log",       view: "admin-audit" },
  ],
  teacher: [
    { icon: BookOpen,        label: "Courses",         view: "teacher-courses" },
    { icon: Inbox,           label: "Submission Queue",view: "teacher-queue" },
  ],
  student: [
    { icon: BookOpen,        label: "Assignments",     view: "student-assignments" },
    { icon: Upload,          label: "Submit report",   view: "student-upload" },
    { icon: Clock,           label: "Track submission", view: "student-status" },
    { icon: Star,            label: "Results",         view: "student-results" },
  ],
};

function Sidebar({ role, view, onViewChange, onRoleChange }: {
  role: Role; view: View;
  onViewChange: (v: View) => void;
  onRoleChange: (r: Role) => void;
}) {
  return (
    <aside className="flex-shrink-0 w-[220px] bg-[#f5f7f9] border-r border-[#e8e8e8] flex flex-col h-full overflow-hidden">
      <div className="px-5 py-4 border-b border-[#e8e8e8] flex items-center gap-2.5">
        <div className="size-7 bg-[#1c1d1d] rounded-lg flex items-center justify-center flex-shrink-0">
          <GraduationCap className="size-4 text-white" />
        </div>
        <span className="text-[15px] font-bold text-[#1c1d1d] tracking-tight">DocGrading</span>
      </div>

      <div className="px-3 py-2.5 border-b border-[#e8e8e8]">
        <select
          value={role}
          onChange={(e) => onRoleChange(e.target.value as Role)}
          className="w-full text-xs px-2.5 py-1.5 bg-white border border-[#e0e0e0] rounded-lg text-[#1c1d1d] outline-none cursor-pointer"
        >
          <option value="admin">Admin</option>
          <option value="teacher">Teacher</option>
          <option value="student">Student</option>
        </select>
      </div>

      <nav className="flex-1 px-3 py-2 space-y-0.5 overflow-y-auto">
        {NAV[role].map((item) => {
          const Icon = item.icon;
          const active = view === item.view;
          return (
            <button
              key={item.view}
              onClick={() => onViewChange(item.view)}
              className={clsx(
                "w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs transition-all text-left",
                active
                  ? "bg-[rgba(28,29,29,0.1)] text-[#1c1d1d] font-semibold shadow-[0_0_63px_rgba(0,0,0,0.07)]"
                  : "text-[#555] hover:bg-[#ebebeb]"
              )}
            >
              <Icon className="size-[18px] flex-shrink-0" />
              <span className="text-[14px]">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="px-3 py-3 border-t border-[#e8e8e8]">
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <div className="size-8 bg-[#1c1d1d] rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold text-white">
            {role === "admin" ? "A" : role === "teacher" ? "T" : "S"}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-[#1c1d1d] truncate">
              {role === "admin" ? "Admin" : role === "teacher" ? "Teacher" : "Student"}
            </p>
            <p className="text-[10px] text-[#8a8a8a] truncate">docgrading.edu.vn</p>
          </div>
        </div>
      </div>
    </aside>
  );
}

// ---- TopBar ----
const BREADCRUMBS: Record<View, string[]> = {
  "admin-dashboard":    ["Admin", "Dashboard"],
  "admin-users":        ["Admin", "Users"],
  "admin-jobs":         ["Admin", "Job Monitoring"],
  "admin-audit":        ["Admin", "Audit Log"],
  "teacher-courses":    ["Teacher", "Courses"],
  "teacher-course":     ["Teacher", "Courses", "Course workspace"],
  "teacher-course-editor": ["Teacher", "Courses", "Course settings"],
  "teacher-assignment-editor": ["Teacher", "Courses", "Assignment editor"],
  "teacher-queue":      ["Teacher", "Submission Queue"],
  "teacher-review":     ["Teacher", "Submission Queue", "Review Workspace"],
  "student-assignments":["Student", "Assignments"],
  "student-upload":     ["Student", "Submit report"],
  "student-status":     ["Student", "Track submission"],
  "student-results":    ["Student", "Results"],
};

function TopBar({ view }: { view: View }) {
  const crumbs = BREADCRUMBS[view] || [];
  return (
    <div className="flex-shrink-0 h-12 bg-white border-b border-[#e8e8e8] flex items-center justify-between px-5">
      <div className="flex items-center gap-1 text-xs text-[#8a8a8a]">
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="size-3" />}
            <span className={clsx(i === crumbs.length - 1 ? "text-[#1c1d1d] font-semibold" : "")}>
              {c}
            </span>
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button className="relative p-1.5 rounded-xl hover:bg-[#f5f7f9] text-[#555] border border-[#e7eae9]">
          <Bell className="size-4" />
          <span className="absolute top-0.5 right-0.5 size-2 bg-red-500 rounded-full border border-white" />
        </button>
      </div>
    </div>
  );
}

// ============================================================
// ADMIN VIEWS
// ============================================================

function AdminDashboard() {
  const stats = [
    { label: "Total users",      value: "1,248", icon: Users,         sub: "+12 this week",       alert: false },
    { label: "Open assignments", value: "7",     icon: Layers,        sub: "3 processing",        alert: false },
    { label: "Queue depth",      value: "34",    icon: ListTodo,      sub: "↑ 8 since yesterday", alert: false },
    { label: "Failed jobs",      value: "3",     icon: XCircle,       sub: "Action required",     alert: true  },
  ];

  const errorJobs = [
    { id: "J-0023", sub: "SUB-003", evaluator: "eval-v2.1", age: "2h 14m", error: "PDF text layer not found" },
    { id: "J-0021", sub: "SUB-008", evaluator: "eval-v2.1", age: "3h 02m", error: "Timeout during criteria evaluation" },
    { id: "J-0019", sub: "SUB-012", evaluator: "eval-v2.0", age: "5h 47m", error: "Evaluator returned invalid JSON" },
  ];

  const recent = [
    { time: "14:32", user: "Minh",       action: "published a result",       target: "SUB-002" },
    { time: "13:15", user: "Nguyễn Văn A", action: "submitted a report",    target: "SUB-001 v2" },
    { time: "12:48", user: "Admin",      action: "Retry job",                 target: "J-0018" },
    { time: "11:30", user: "System",     action: "completed an evaluation",  target: "SUB-006" },
    { time: "10:20", user: "Hà",         action: "overrode a score",         target: "SUB-005 C3" },
  ];

  return (
    <div className="p-6 space-y-5 max-w-[1200px]">
      <div className="flex items-center gap-3 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm">
        <AlertTriangle className="size-4 text-red-600 flex-shrink-0" />
        <span className="text-red-700 font-medium text-xs">3 failed jobs require attention</span>
        <button className="ml-auto text-red-600 text-xs font-semibold hover:underline">Review now →</button>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className={clsx(
              "bg-white border rounded-2xl p-4 shadow-[0_0_8px_rgba(0,0,0,0.06)] space-y-3",
              s.alert ? "border-red-200" : "border-[#e7eae9]"
            )}>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#85878d]">{s.label}</span>
                <div className={clsx("size-8 rounded-xl flex items-center justify-center", s.alert ? "bg-red-50" : "bg-[#f5f7f9]")}>
                  <Icon className={clsx("size-4", s.alert ? "text-red-500" : "text-[#42404c]")} />
                </div>
              </div>
              <p className={clsx("text-3xl font-extrabold tracking-tight", s.alert ? "text-red-600" : "text-[#1c1d1d]")}>{s.value}</p>
              <p className="text-[11px] text-[#85878d]">{s.sub}</p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-[1fr_300px] gap-4">
        <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
          <div className="flex items-center justify-between px-5 py-3 border-b border-[#f0f0f0]">
            <h3 className="text-sm font-semibold text-[#1c1d1d]">Failed jobs</h3>
            <button className="text-xs text-[#85878d] hover:text-[#1c1d1d]">View all</button>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-[#f8f8f8]">
              <tr className="text-[#85878d] text-left">
                {["Job ID", "Submission", "Evaluator", "Age", "Error", ""].map(h => (
                  <th key={h} className="px-5 py-2.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#f5f5f5]">
              {errorJobs.map((j) => (
                <tr key={j.id} className="hover:bg-[#fafafa]">
                  <td className="px-5 py-3 font-semibold text-[#1c1d1d]">{j.id}</td>
                  <td className="px-5 py-3 text-[#42404c]">{j.sub}</td>
                  <td className="px-5 py-3 text-[#42404c]">{j.evaluator}</td>
                  <td className="px-5 py-3 text-[#85878d]">{j.age}</td>
                  <td className="px-5 py-3 text-red-600 max-w-[180px] truncate">{j.error}</td>
                  <td className="px-5 py-3">
                    <button className="flex items-center gap-1 px-2.5 py-1 text-[#42404c] border border-[#e7eae9] rounded-lg hover:bg-[#f5f7f9] text-[11px] font-medium">
                      <RotateCcw className="size-3" /> Retry
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
          <div className="px-5 py-3 border-b border-[#f0f0f0]">
            <h3 className="text-sm font-semibold text-[#1c1d1d]">Recent activity</h3>
          </div>
          <div className="divide-y divide-[#f5f5f5]">
            {recent.map((r, i) => (
              <div key={i} className="flex items-start gap-3 px-5 py-3">
                <span className="text-[10px] text-[#85878d] mt-0.5 flex-shrink-0 w-9 font-mono">{r.time}</span>
                <div className="min-w-0">
                  <p className="text-xs text-[#1c1d1d]"><span className="font-semibold">{r.user}</span> {r.action}</p>
                  <p className="text-[10px] text-[#85878d]">{r.target}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AdminUsers() {
  const users = [
    { name: "Nguyễn Minh",        email: "nminh@uni.edu.vn",             role: "teacher", status: "active" },
    { name: "Trần Hà",            email: "tha@uni.edu.vn",               role: "teacher", status: "active" },
    { name: "Nguyễn Văn A",       email: "20210001@student.uni.edu.vn",  role: "student", status: "active" },
    { name: "Trần Thị B",         email: "20210002@student.uni.edu.vn",  role: "student", status: "active" },
    { name: "System Admin",       email: "admin@uni.edu.vn",             role: "admin",   status: "active" },
    { name: "Lê Văn C",           email: "20210003@student.uni.edu.vn",  role: "student", status: "locked" },
  ];
  return (
    <div className="p-6 space-y-4 max-w-[1000px]">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-[#1c1d1d]">User management</h2>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-1.5 border border-[#e7eae9] rounded-xl bg-white text-xs">
            <Search className="size-3.5 text-[#85878d]" />
            <input className="outline-none w-36 bg-transparent placeholder-[#85878d] text-xs" placeholder="Search users..." />
          </div>
          <select className="text-xs px-3 py-1.5 border border-[#e7eae9] rounded-xl bg-white outline-none text-[#42404c]">
            <option>All roles</option>
            <option>Admin</option>
            <option>Teacher</option>
            <option>Student</option>
          </select>
        </div>
      </div>
      <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <table className="w-full text-xs">
          <thead className="bg-[#f8f8f8]">
            <tr className="text-[#85878d] text-left">
              {["Name", "Email", "Role", "Status", ""].map(h => (
                <th key={h} className="px-5 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f5f5f5]">
            {users.map((u, i) => (
              <tr key={i} className="hover:bg-[#fafafa]">
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <div className="size-7 bg-[#e8e8e8] rounded-full flex items-center justify-center text-[10px] font-bold text-[#42404c]">
                      {u.name[0]}
                    </div>
                    <span className="font-semibold text-[#1c1d1d]">{u.name}</span>
                  </div>
                </td>
                <td className="px-5 py-3 text-[#42404c]">{u.email}</td>
                <td className="px-5 py-3">
                  <span className={clsx("px-2 py-0.5 rounded-full text-[10px] font-semibold",
                    u.role === "admin" ? "bg-[#1c1d1d] text-white" :
                    u.role === "teacher" ? "bg-blue-50 text-blue-700" : "bg-[#f0f0f0] text-[#42404c]"
                  )}>
                    {u.role === "admin" ? "Admin" : u.role === "teacher" ? "Teacher" : "Student"}
                  </span>
                </td>
                <td className="px-5 py-3">
                  <span className={clsx("px-2 py-0.5 rounded-full text-[10px] font-semibold",
                    u.status === "active" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                  )}>
                    {u.status === "active" ? "Active" : "Locked"}
                  </span>
                </td>
                <td className="px-5 py-3">
                  <button className="text-[#85878d] hover:text-[#1c1d1d]">
                    <MoreHorizontal className="size-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminJobs() {
  const jobs = [
    { id: "J-0023", sub: "SUB-003", eval: "eval-v2.1", status: "error",   age: "2h 14m", duration: "—",    error: "PDF text layer not found" },
    { id: "J-0022", sub: "SUB-006", eval: "eval-v2.1", status: "running", age: "0h 08m", duration: "8m",   error: null },
    { id: "J-0021", sub: "SUB-008", eval: "eval-v2.1", status: "error",   age: "3h 02m", duration: "—",    error: "Timeout during evaluation" },
    { id: "J-0020", sub: "SUB-009", eval: "eval-v2.0", status: "done",    age: "4h 30m", duration: "12m",  error: null },
    { id: "J-0019", sub: "SUB-012", eval: "eval-v2.0", status: "error",   age: "5h 47m", duration: "—",    error: "Evaluator returned invalid JSON" },
    { id: "J-0018", sub: "SUB-010", eval: "eval-v2.1", status: "done",    age: "6h 05m", duration: "9m",   error: null },
  ];
  return (
    <div className="p-6 space-y-4 max-w-[1000px]">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-[#1c1d1d]">Job Monitoring</h2>
          <p className="text-xs text-[#85878d] mt-0.5">34 jobs queued · 3 failed · 2 running</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="text-xs px-3 py-1.5 border border-[#e7eae9] rounded-xl bg-white outline-none text-[#42404c]">
            <option>All statuses</option>
            <option>Failed</option>
            <option>Running</option>
            <option>Completed</option>
          </select>
        </div>
      </div>
      <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <table className="w-full text-xs">
          <thead className="bg-[#f8f8f8]">
            <tr className="text-[#85878d] text-left">
              {["Job ID", "Submission", "Evaluator", "Status", "Age", "Duration", "Error", ""].map(h => (
                <th key={h} className="px-5 py-2.5 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f5f5f5]">
            {jobs.map((j) => (
              <tr key={j.id} className="hover:bg-[#fafafa]">
                <td className="px-5 py-3 font-semibold text-[#1c1d1d] font-mono">{j.id}</td>
                <td className="px-5 py-3 text-[#42404c]">{j.sub}</td>
                <td className="px-5 py-3 text-[#42404c]">{j.eval}</td>
                <td className="px-5 py-3">
                  <span className={clsx("px-2 py-0.5 rounded-full text-[10px] font-semibold",
                    j.status === "error" ? "bg-red-100 text-red-700" :
                    j.status === "running" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
                  )}>
                    {j.status === "error" ? "Failed" : j.status === "running" ? "Running" : "Completed"}
                  </span>
                </td>
                <td className="px-5 py-3 text-[#85878d]">{j.age}</td>
                <td className="px-5 py-3 text-[#85878d]">{j.duration}</td>
                <td className="px-5 py-3 text-red-600 max-w-[160px] truncate">{j.error || "—"}</td>
                <td className="px-5 py-3">
                  {j.status === "error" && (
                    <button className="flex items-center gap-1 px-2.5 py-1 text-[#42404c] border border-[#e7eae9] rounded-lg hover:bg-[#f5f7f9] text-[11px] font-medium">
                      <RotateCcw className="size-3" /> Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminAuditLog() {
  const logs = [
    { time: "15/07 14:32", user: "Minh",  action: "PUBLISH_RESULT",  target: "SUB-002",     detail: "Published result for Trần Thị B" },
    { time: "15/07 13:48", user: "Hà",    action: "OVERRIDE_SCORE",  target: "SUB-005 C3",  detail: "Adjusted score from 14 → 16" },
    { time: "15/07 12:30", user: "Admin", action: "RETRY_JOB",       target: "J-0017",      detail: "Retried job after timeout" },
    { time: "15/07 11:15", user: "Admin", action: "ROLE_CHANGE",     target: "U04",         detail: "Assigned Teacher role to nminh@uni.edu.vn" },
    { time: "15/07 10:00", user: "System", action: "EVAL_COMPLETE",  target: "SUB-006",     detail: "Evaluation completed, confidence: 0.95" },
    { time: "14/07 17:22", user: "Minh",  action: "APPROVE",         target: "SUB-006",     detail: "Approved evaluation result" },
  ];
  const actionCls: Record<string, string> = {
    PUBLISH_RESULT: "bg-green-100 text-green-800",
    OVERRIDE_SCORE: "bg-orange-100 text-orange-800",
    RETRY_JOB:      "bg-blue-100 text-blue-800",
    ROLE_CHANGE:    "bg-violet-100 text-violet-800",
    EVAL_COMPLETE:  "bg-gray-100 text-gray-700",
    APPROVE:        "bg-green-50 text-green-700",
  };
  return (
    <div className="p-6 space-y-4 max-w-[1000px]">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-[#1c1d1d]">Audit Log</h2>
        <select className="text-xs px-3 py-1.5 border border-[#e7eae9] rounded-xl bg-white outline-none text-[#42404c]">
          <option>All actions</option>
          <option>Publish</option>
          <option>Override</option>
          <option>Role Change</option>
        </select>
      </div>
      <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <table className="w-full text-xs">
          <thead className="bg-[#f8f8f8]">
            <tr className="text-[#85878d] text-left">
              {["Time", "User", "Action", "Target", "Details"].map(h => (
                <th key={h} className="px-5 py-2.5 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f5f5f5]">
            {logs.map((l, i) => (
              <tr key={i} className="hover:bg-[#fafafa]">
                <td className="px-5 py-3 text-[#85878d] whitespace-nowrap font-mono">{l.time}</td>
                <td className="px-5 py-3 font-semibold text-[#1c1d1d]">{l.user}</td>
                <td className="px-5 py-3">
                  <span className={clsx("px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold", actionCls[l.action] || "bg-gray-100 text-gray-600")}>
                    {l.action}
                  </span>
                </td>
                <td className="px-5 py-3 text-[#42404c] font-mono">{l.target}</td>
                <td className="px-5 py-3 text-[#42404c] max-w-[280px] truncate">{l.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================
// TEACHER VIEWS
// ============================================================

function CourseCatalog({ courses, assignments, onSelect, onCreate }: {
  courses: Course[];
  assignments: Assignment[];
  onSelect: (course: Course) => void;
  onCreate: () => void;
}) {
  return (
    <div className="p-6 space-y-5 max-w-[980px]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-[#1c1d1d]">Courses</h2>
          <p className="text-xs text-[#85878d] mt-0.5">Organize assignments, rubrics and submissions by course.</p>
        </div>
        <button onClick={onCreate} className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333]">
          <Plus className="size-3.5" /> Create course
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {courses.map((course) => {
          const courseAssignments = assignments.filter((item) => item.courseId === course.id);
          const open = courseAssignments.filter((item) => item.status === "open").length;
          const pending = courseAssignments.reduce((sum, item) => sum + Math.max(0, item.submitted - item.reviewed), 0);
          return (
            <button key={course.id} onClick={() => onSelect(course)} className="bg-white border border-[#e7eae9] rounded-2xl p-5 text-left shadow-[0_0_8px_rgba(0,0,0,0.04)] hover:shadow-[0_0_14px_rgba(0,0,0,0.08)] hover:border-[#d8d8d8] transition-all group">
              <div className="flex items-start gap-3">
                <div className="size-10 rounded-xl bg-[#f1f2f3] border border-[#e7eae9] flex items-center justify-center flex-shrink-0">
                  <BookOpen className="size-5 text-[#42404c]" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-[10px] font-bold tracking-[0.08em] text-[#85878d] uppercase">{course.code}</p>
                    {open > 0 && <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold bg-green-100 text-green-700">{open} open</span>}
                  </div>
                  <h3 className="text-sm font-bold text-[#1c1d1d] mt-1 truncate">{course.name}</h3>
                  <p className="text-[11px] text-[#85878d] mt-0.5">{course.term}</p>
                </div>
                <ChevronRight className="size-4 text-[#b1b1b1] group-hover:text-[#1c1d1d] transition-colors mt-1" />
              </div>
              <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-[#f1f1f1]">
                {[
                  ["Students", course.students],
                  ["Assignments", courseAssignments.length],
                  ["To review", pending],
                ].map(([label, value]) => (
                  <div key={label as string}>
                    <p className="text-[10px] text-[#85878d]">{label}</p>
                    <p className="text-sm font-bold text-[#1c1d1d] mt-0.5">{value}</p>
                  </div>
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CourseWorkspace({ course, assignments, onBack, onEditCourse, onCreateAssignment, onEditAssignment, onQueue }: {
  course: Course;
  assignments: Assignment[];
  onBack: () => void;
  onEditCourse: () => void;
  onCreateAssignment: () => void;
  onEditAssignment: (assignment: Assignment) => void;
  onQueue: (assignment: Assignment) => void;
}) {
  return (
    <div className="p-6 space-y-5 max-w-[1040px]">
      <button onClick={onBack} className="text-xs text-[#42404c] hover:text-[#1c1d1d] flex items-center gap-1 font-medium">
        <ChevronLeft className="size-4" /> All courses
      </button>

      <div className="bg-white border border-[#e7eae9] rounded-2xl p-5 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="size-11 rounded-xl bg-[#1c1d1d] flex items-center justify-center flex-shrink-0">
              <BookOpen className="size-5 text-white" />
            </div>
            <div>
              <p className="text-[10px] font-bold tracking-[0.08em] text-[#85878d] uppercase">{course.code}</p>
              <h2 className="text-lg font-bold text-[#1c1d1d] mt-0.5">{course.name}</h2>
              <p className="text-xs text-[#85878d] mt-1">{course.term} · {course.students} students</p>
            </div>
          </div>
          <button onClick={onEditCourse} className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">
            <Settings className="size-3.5" /> Course settings
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-[#1c1d1d]">Assignments</h3>
          <p className="text-[11px] text-[#85878d] mt-0.5">Define what students submit, how it is evaluated and when results are released.</p>
        </div>
        <button onClick={onCreateAssignment} className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333]">
          <Plus className="size-3.5" /> New assignment
        </button>
      </div>

      <div className="space-y-3">
        {assignments.length === 0 && (
          <div className="bg-white border border-dashed border-[#dcdcdc] rounded-2xl py-12 text-center">
            <FileText className="size-6 text-[#aaa] mx-auto mb-2" />
            <p className="text-xs font-semibold text-[#42404c]">No assignments yet</p>
            <p className="text-[11px] text-[#85878d] mt-1">Create the first assignment for this course.</p>
          </div>
        )}
        {assignments.map((assignment) => (
          <div key={assignment.id} className="bg-white border border-[#e7eae9] rounded-2xl p-5 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="text-sm font-bold text-[#1c1d1d] truncate">{assignment.title}</h4>
                  <span className={clsx("text-[10px] px-2 py-0.5 rounded-full font-semibold",
                    assignment.status === "open" ? "bg-green-100 text-green-700" :
                    assignment.status === "closed" ? "bg-[#1c1d1d] text-white" :
                    "bg-[#f0f0f0] text-[#42404c]"
                  )}>
                    {assignment.status === "open" ? "Open" : assignment.status === "closed" ? "Closed" : "Draft"}
                  </span>
                </div>
                <p className="text-[11px] text-[#85878d] line-clamp-1">{assignment.description}</p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[10px] text-[#85878d]">
                  <span>Due {assignment.dueDate}</span>
                  <span>{assignment.attempts} submission attempts</span>
                  <span>PDF · text layer required</span>
                  <span>{assignment.rubric}</span>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button onClick={() => onEditAssignment(assignment)} className="flex items-center gap-1 px-3 py-1.5 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">
                  <Pencil className="size-3.5" /> Edit
                </button>
                <button onClick={() => onQueue(assignment)} className="flex items-center gap-1 px-3 py-1.5 text-xs text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333] font-semibold">
                  Open submissions <ChevronRight className="size-3.5" />
                </button>
              </div>
            </div>
            <div className="flex gap-8 mt-4 pt-3 border-t border-[#f5f5f5]">
              {[["Submitted", assignment.submitted], ["Reviewed", assignment.reviewed], ["Published", assignment.published]].map(([label, value]) => (
                <div key={label as string} className="text-xs">
                  <span className="text-[#85878d]">{label}: </span>
                  <span className="font-bold text-[#1c1d1d]">{value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CourseEditor({ course, onBack, onSave }: { course: Course | null; onBack: () => void; onSave: (course: Course) => void }) {
  const [code, setCode] = useState(course?.code ?? "");
  const [name, setName] = useState(course?.name ?? "");
  const [term, setTerm] = useState(course?.term ?? "Semester 1 · 2025");

  return (
    <div className="p-6 max-w-[620px]">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onBack} className="text-xs text-[#42404c] hover:text-[#1c1d1d] flex items-center gap-1 font-medium">
          <ChevronLeft className="size-4" /> Back
        </button>
        <h2 className="text-lg font-bold text-[#1c1d1d]">{course ? "Course settings" : "Create course"}</h2>
      </div>
      <div className="bg-white border border-[#e7eae9] rounded-2xl p-6 shadow-[0_0_8px_rgba(0,0,0,0.04)] space-y-4">
        <div>
          <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Course code *</label>
          <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="e.g. INT2208-01" className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none focus:border-[#1c1d1d] bg-[#f8f8f8] placeholder-[#aaa]" />
        </div>
        <div>
          <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Course name *</label>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Course names may use the teaching language" className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none focus:border-[#1c1d1d] bg-[#f8f8f8] placeholder-[#aaa]" />
        </div>
        <div>
          <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Term *</label>
          <input value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Semester 1 · 2025" className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none focus:border-[#1c1d1d] bg-[#f8f8f8] placeholder-[#aaa]" />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <button onClick={onBack} className="px-4 py-2 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">Cancel</button>
        <button disabled={!code.trim() || !name.trim()} onClick={() => onSave({ id: course?.id ?? `COURSE-${Date.now()}`, code: code.trim(), name: name.trim(), term: term.trim(), students: course?.students ?? 0 })} className="px-4 py-2 text-xs text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333] disabled:opacity-40 disabled:cursor-not-allowed font-semibold">
          Save course
        </button>
      </div>
    </div>
  );
}

function AssignmentEditor({ course, assignment, onBack, onSave }: {
  course: Course;
  assignment: Assignment | null;
  onBack: () => void;
  onSave: (assignment: Assignment) => void;
}) {
  const [step, setStep] = useState(1);
  const [title, setTitle] = useState(assignment?.title ?? "");
  const [description, setDescription] = useState(assignment?.description ?? "");
  const [dueDate, setDueDate] = useState(assignment?.dueDate ?? "2024-08-31");
  const [attempts, setAttempts] = useState(assignment?.attempts ?? 3);
  const [rubric, setRubric] = useState(assignment?.rubric ?? "SRS Standard v2.1");
  const [templateName, setTemplateName] = useState(assignment?.templateName ?? "SRS-template.docx");
  const [requireAppendix, setRequireAppendix] = useState(assignment?.requireAppendix ?? false);
  const steps = ["Details", "Submission requirements", "Rubric", "Review"];
  const weight = CRITERIA.reduce((sum, criterion) => sum + criterion.weight, 0);

  const save = (status: Assignment["status"]) => onSave({
    id: assignment?.id ?? `ASG-${Date.now()}`,
    courseId: course.id,
    title: title.trim() || "Untitled assignment",
    description: description.trim(),
    dueDate,
    attempts,
    status,
    submitted: assignment?.submitted ?? 0,
    reviewed: assignment?.reviewed ?? 0,
    published: assignment?.published ?? 0,
    rubric,
    requireAppendix,
    templateName,
  });

  return (
    <div className="p-6 max-w-[760px]">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onBack} className="text-xs text-[#42404c] hover:text-[#1c1d1d] flex items-center gap-1 font-medium">
          <ChevronLeft className="size-4" /> {course.name}
        </button>
        <div>
          <h2 className="text-lg font-bold text-[#1c1d1d]">{assignment ? "Edit assignment" : "Create assignment"}</h2>
          <p className="text-[10px] text-[#85878d] mt-0.5">Drafts are saved per assignment and are not visible to students.</p>
        </div>
      </div>

      <div className="flex items-center gap-0 mb-8">
        {steps.map((label, index) => {
          const number = index + 1;
          const done = step > number;
          const active = step === number;
          return (
            <div key={label} className="flex items-center flex-1 last:flex-none">
              <div className="flex items-center gap-2 flex-shrink-0">
                <div className={clsx("size-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all",
                  done ? "bg-[#1c1d1d] border-[#1c1d1d] text-white" : active ? "border-[#1c1d1d] text-[#1c1d1d]" : "border-[#ddd] text-[#aaa]"
                )}>
                  {done ? <Check className="size-3.5" /> : number}
                </div>
                <span className={clsx("text-[11px] font-medium whitespace-nowrap hidden sm:block", active ? "text-[#1c1d1d]" : done ? "text-[#42404c]" : "text-[#aaa]")}>{label}</span>
              </div>
              {index < steps.length - 1 && <div className={clsx("flex-1 h-px mx-2", step > number ? "bg-[#1c1d1d]" : "bg-[#e0e0e0]")} />}
            </div>
          );
        })}
      </div>

      <div className="bg-white border border-[#e7eae9] rounded-2xl p-6 shadow-[0_0_8px_rgba(0,0,0,0.04)] space-y-4">
        {step === 1 && (
          <>
            <div>
              <h3 className="text-sm font-bold text-[#1c1d1d]">Assignment details</h3>
              <p className="text-[11px] text-[#85878d] mt-1">Give students enough context before they open the submission form.</p>
            </div>
            <div>
              <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Assignment title *</label>
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Software Requirements Specification" className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none focus:border-[#1c1d1d] bg-[#f8f8f8] placeholder-[#aaa]" />
            </div>
            <div>
              <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Description and instructions *</label>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the task, expected structure and any preparation students need." className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none focus:border-[#1c1d1d] bg-[#f8f8f8] resize-none h-24 placeholder-[#aaa]" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Due date *</label>
                <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none bg-[#f8f8f8]" />
              </div>
              <div>
                <label className="text-xs font-semibold text-[#42404c] block mb-1.5">Submission attempts</label>
                <select value={attempts} onChange={(event) => setAttempts(Number(event.target.value))} className="w-full px-3 py-2 text-xs border border-[#e7eae9] rounded-xl outline-none bg-[#f8f8f8]">
                  {[1, 2, 3, 4, 5].map((value) => <option key={value} value={value}>{value} attempt{value > 1 ? "s" : ""}</option>)}
                </select>
              </div>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <h3 className="text-sm font-bold text-[#1c1d1d]">Submission requirements</h3>
              <p className="text-[11px] text-[#85878d] mt-1">Choose exactly what students must provide for this assignment.</p>
            </div>
            <div className="space-y-2">
              <label className="flex items-start gap-3 p-3.5 border border-[#1c1d1d] bg-[#f8f8f8] rounded-xl">
                <input type="checkbox" checked readOnly className="mt-0.5 accent-[#1c1d1d]" />
                <div className="flex-1">
                  <p className="text-xs font-semibold text-[#1c1d1d]">Main report · PDF</p>
                  <p className="text-[10px] text-[#85878d] mt-0.5">Required · maximum 50 MB · text layer required · scanned pages rejected</p>
                </div>
                <span className="text-[10px] font-semibold text-[#42404c]">Required</span>
              </label>
              <label className="flex items-start gap-3 p-3.5 border border-[#e7eae9] rounded-xl cursor-pointer hover:bg-[#f8f8f8]">
                <input type="checkbox" checked={requireAppendix} onChange={(event) => setRequireAppendix(event.target.checked)} className="mt-0.5 accent-[#1c1d1d]" />
                <div className="flex-1">
                  <p className="text-xs font-semibold text-[#1c1d1d]">Supporting appendix</p>
                  <p className="text-[10px] text-[#85878d] mt-0.5">Optional supplementary PDF for references or extended evidence.</p>
                </div>
              </label>
            </div>
            <div className="border-t border-[#f1f1f1] pt-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold text-[#42404c]">Student template</p>
                  <p className="text-[10px] text-[#85878d] mt-0.5">Attach a structure template or sample document.</p>
                </div>
                <label className="px-3 py-1.5 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium cursor-pointer">
                  <input type="file" className="hidden" onChange={(event) => setTemplateName(event.target.files?.[0]?.name ?? templateName)} />
                  Replace file
                </label>
              </div>
              <div className="mt-2.5 flex items-center gap-2 bg-[#f8f8f8] border border-[#e7eae9] rounded-xl px-3 py-2.5">
                <FileText className="size-4 text-[#42404c]" />
                <span className="text-xs font-medium text-[#1c1d1d] flex-1 truncate">{templateName}</span>
                <button onClick={() => setTemplateName("No template attached")} className="text-[#85878d] hover:text-[#1c1d1d]"><X className="size-3.5" /></button>
              </div>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-[#1c1d1d]">Rubric and criteria</h3>
                <p className="text-[11px] text-[#85878d] mt-1">Clone a system rubric before editing. Published versions remain immutable.</p>
              </div>
              <span className={clsx("text-xs font-semibold px-2.5 py-1 rounded-full", weight === 100 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700")}>Total {weight}%</span>
            </div>
            <div className="space-y-2">
              {["SRS Standard v2.1", "Software Design v1.0", "Thesis Template v1.0"].map((name) => (
                <label key={name} className={clsx("flex items-center gap-3 p-3 border rounded-xl cursor-pointer hover:bg-[#f8f8f8] transition-colors", rubric === name ? "border-[#1c1d1d] bg-[#f8f8f8]" : "border-[#e7eae9]")}>
                  <input type="radio" name="rubric" checked={rubric === name} onChange={() => setRubric(name)} className="accent-[#1c1d1d]" />
                  <div className="flex-1">
                    <p className="text-xs font-semibold text-[#1c1d1d]">{name}</p>
                    <p className="text-[10px] text-[#85878d]">5 criteria · versioned · evidence required</p>
                  </div>
                  <button type="button" className="text-[10px] text-blue-600 hover:underline font-medium" onClick={(event) => event.preventDefault()}>Clone</button>
                </label>
              ))}
            </div>
            <div className="space-y-2 pt-2 border-t border-[#f1f1f1]">
              {CRITERIA.map((criterion) => (
                <div key={criterion.id} className="flex items-center gap-3 p-3 border border-[#e7eae9] rounded-xl hover:bg-[#f8f8f8]">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-[#1c1d1d] truncate">{criterion.name}</p>
                    <p className="text-[10px] text-[#85878d]">Hybrid evaluator · evidence required</p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <input type="number" defaultValue={criterion.weight} aria-label={`${criterion.name} weight`} className="w-12 px-2 py-1 text-xs border border-[#e7eae9] rounded-lg text-center outline-none bg-[#f8f8f8]" />
                    <span className="text-xs text-[#85878d]">%</span>
                  </div>
                  <button className="p-1 text-[#85878d] hover:text-[#1c1d1d]" aria-label={`Edit ${criterion.name}`}><Pencil className="size-3.5" /></button>
                </div>
              ))}
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <div>
              <h3 className="text-sm font-bold text-[#1c1d1d]">Review and publish</h3>
              <p className="text-[11px] text-[#85878d] mt-1">Confirm student-facing requirements before opening submissions.</p>
            </div>
            <div className="bg-[#f8f8f8] rounded-xl p-4 space-y-2 text-xs border border-[#e7eae9]">
              {[
                ["Course", `${course.code} · ${course.name}`],
                ["Assignment", title || "Untitled assignment"],
                ["Due date", dueDate],
                ["Deliverables", requireAppendix ? "Main PDF + supporting appendix" : "Main PDF"],
                ["Attempts", String(attempts)],
                ["Rubric", rubric],
                ["Criteria", `${CRITERIA.length} criteria · ${weight}% total`],
              ].map(([key, value]) => (
                <div key={key} className="flex justify-between gap-4">
                  <span className="text-[#85878d]">{key}:</span>
                  <span className="font-semibold text-[#1c1d1d] text-right">{value}</span>
                </div>
              ))}
            </div>
            <div className="flex items-start gap-3 p-3 bg-green-50 rounded-xl border border-green-200 text-xs text-green-700">
              <CheckCircle className="size-4 flex-shrink-0 mt-0.5" />
              <span>Requirements are complete, rubric weight is 100%, and the assignment is ready to publish.</span>
            </div>
          </>
        )}
      </div>

      <div className="flex justify-between gap-3 mt-5">
        <div className="flex items-center gap-2">
          <button onClick={() => step > 1 ? setStep(step - 1) : onBack()} className="flex items-center gap-1.5 px-4 py-2 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">
            <ChevronLeft className="size-3.5" /> {step > 1 ? "Back" : "Cancel"}
          </button>
          <button onClick={() => save("draft")} className="px-4 py-2 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">Save draft</button>
        </div>
        {step < 4 ? (
          <button disabled={step === 1 && (!title.trim() || !description.trim())} onClick={() => setStep(step + 1)} className="flex items-center gap-1.5 px-4 py-2 text-xs text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333] disabled:opacity-40 disabled:cursor-not-allowed font-semibold">
            Continue <ChevronRight className="size-3.5" />
          </button>
        ) : (
          <button onClick={() => save("open")} className="flex items-center gap-1.5 px-4 py-2 text-xs text-white bg-green-600 rounded-xl hover:bg-green-700 font-semibold">
            <Check className="size-3.5" /> {assignment ? "Update and publish" : "Publish assignment"}
          </button>
        )}
      </div>
    </div>
  );
}

function SubmissionQueue({ assignmentName, onSelect }: { assignmentName: string; onSelect: (sub: typeof SUBMISSIONS[0]) => void }) {
  type Filter = Status | "all";
  const [activeFilter, setActiveFilter] = useState<Filter>("all");

  const tabs: Array<{ key: Filter; label: string }> = [
    { key: "all",              label: "All" },
    { key: "needs-review",     label: "Needs review" },
    { key: "pending-approval", label: "Pending approval" },
    { key: "approved",         label: "Approved" },
    { key: "published",        label: "Published" },
    { key: "error",            label: "Failed" },
  ];

  const rows = activeFilter === "all" ? SUBMISSIONS : SUBMISSIONS.filter(s => s.status === activeFilter);

  return (
    <div className="p-6 space-y-4 max-w-[1100px]">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-[#1c1d1d]">Submission Queue</h2>
          <p className="text-xs text-[#85878d] mt-0.5">{assignmentName} · {SUBMISSIONS.length} submissions</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-[#42404c] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-medium">
            <Filter className="size-3.5" /> Filter
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333] font-semibold">
            <ArrowRight className="size-3.5" /> Next unreviewed
          </button>
        </div>
      </div>

      <div className="flex gap-1 bg-[#f5f7f9] p-1 rounded-xl w-fit border border-[#e7eae9]">
        {tabs.map((t) => {
          const count = t.key === "all" ? SUBMISSIONS.length : SUBMISSIONS.filter(s => s.status === t.key).length;
          return (
            <button key={t.key} onClick={() => setActiveFilter(t.key)}
              className={clsx("px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                activeFilter === t.key ? "bg-white text-[#1c1d1d] shadow-sm" : "text-[#85878d] hover:text-[#42404c]"
              )}>
              {t.label} <span className="ml-1 text-[10px] opacity-60">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <table className="w-full text-xs">
          <thead className="bg-[#f8f8f8]">
            <tr className="text-[#85878d] text-left">
              {["Student", "Version", "Submitted", "Status", "Suggested", "Confidence", "Reviewer", ""].map(h => (
                <th key={h} className="px-5 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#f5f5f5]">
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-5 py-10 text-center text-xs text-[#85878d]">
                  No submissions match this status
                </td>
              </tr>
            )}
            {rows.map((sub) => (
              <tr key={sub.id} className="hover:bg-[#fafafa] cursor-pointer" onClick={() => onSelect(sub)}>
                <td className="px-5 py-3.5">
                  <p className="font-semibold text-[#1c1d1d]">{sub.student}</p>
                  <p className="text-[10px] text-[#85878d]">{sub.studentId}</p>
                </td>
                <td className="px-5 py-3.5 text-[#42404c]">v{sub.version}</td>
                <td className="px-5 py-3.5 text-[#85878d] whitespace-nowrap">{sub.submittedAt}</td>
                <td className="px-5 py-3.5"><StatusBadge status={sub.status} /></td>
                <td className="px-5 py-3.5">
                  {sub.suggestedScore !== null
                    ? <span className="font-bold text-[#1c1d1d]">{sub.suggestedScore.toFixed(1)}</span>
                    : <span className="text-[#ddd]">—</span>}
                </td>
                <td className="px-5 py-3.5">
                  {sub.confidence !== null ? (
                    <div className="flex items-center gap-2">
                      <div className="w-14 h-1.5 bg-[#e8e8e8] rounded-full overflow-hidden">
                        <div className="h-full bg-[#42404c] rounded-full" style={{ width: `${sub.confidence * 100}%` }} />
                      </div>
                      <span className="text-[#42404c] font-medium">{Math.round(sub.confidence * 100)}%</span>
                    </div>
                  ) : <span className="text-[#ddd]">—</span>}
                </td>
                <td className="px-5 py-3.5">
                  {sub.reviewer ? <span className="text-[#42404c]">{sub.reviewer}</span> : <span className="text-[#ddd]">—</span>}
                </td>
                <td className="px-5 py-3.5">
                  {(sub.status === "needs-review" || sub.status === "pending-approval") && (
                    <button
                      className="flex items-center gap-1 px-2.5 py-1.5 text-[#1c1d1d] border border-[#e7eae9] rounded-xl hover:bg-[#f5f7f9] font-semibold text-[11px]"
                      onClick={e => { e.stopPropagation(); onSelect(sub); }}
                    >
                      Review →
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ReviewWorkspace({ submission, onBack }: { submission: typeof SUBMISSIONS[0]; onBack: () => void }) {
  const [selectedCrit, setSelectedCrit] = useState<string | null>("C2");
  const [critStates, setCritStates] = useState<Record<string, "accepted" | "pending" | "rejected">>(
    Object.fromEntries(CRITERIA.map(c => [c.id, c.status]))
  );
  const [scores, setScores] = useState<Record<string, number>>(
    Object.fromEntries(CRITERIA.map(c => [c.id, c.suggestedScore]))
  );
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">("saved");
  const [page, setPage] = useState(12);

  const crit = CRITERIA.find(c => c.id === selectedCrit);
  const findings = FINDINGS.filter(f => f.criterionId === selectedCrit);

  const totalScore = (CRITERIA.reduce((s, c) => s + scores[c.id], 0) / CRITERIA.reduce((s, c) => s + c.weight, 0)) * 10;

  const accept = (id: string) => { setCritStates(s => ({ ...s, [id]: "accepted" })); save(); };
  const reject = (id: string) => { setCritStates(s => ({ ...s, [id]: "rejected" })); save(); };
  const save = () => { setSaveState("saving"); setTimeout(() => setSaveState("saved"), 700); };

  return (
    <div className="flex h-full overflow-hidden">
      {/* PDF Area */}
      <div className="flex-1 flex flex-col bg-[#f5f7f9] border-r border-[#e7eae9] min-w-0 overflow-hidden">
        {/* Toolbar */}
        <div className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-white border-b border-[#e7eae9]">
          <button onClick={onBack} className="flex items-center gap-1 text-xs text-[#42404c] hover:text-[#1c1d1d] font-medium mr-1">
            <ChevronLeft className="size-4" /> Back to queue
          </button>
          <div className="h-4 w-px bg-[#e7eae9]" />
          <button onClick={() => setPage(p => Math.max(1, p - 1))} className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]">
            <ChevronLeft className="size-4" />
          </button>
          <span className="text-xs text-[#42404c] min-w-[80px] text-center">
            Page <span className="font-bold text-[#1c1d1d]">{page}</span> / {submission.pages || 48}
          </span>
          <button onClick={() => setPage(p => Math.min(submission.pages || 48, p + 1))} className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]">
            <ChevronRight className="size-4" />
          </button>
          <div className="flex-1" />
          <button className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]"><ZoomOut className="size-4" /></button>
          <span className="text-xs text-[#85878d]">100%</span>
          <button className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]"><ZoomIn className="size-4" /></button>
          <div className="h-4 w-px bg-[#e7eae9]" />
          <button className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]"><Search className="size-4" /></button>
          <button className="p-1.5 rounded-lg hover:bg-[#f5f7f9] text-[#42404c]"><Download className="size-4" /></button>
        </div>

        {/* PDF Content */}
        <div className="flex-1 overflow-auto p-6">
          <div className="max-w-[640px] mx-auto bg-white shadow-[0_0_16px_rgba(0,0,0,0.08)] rounded-lg border border-[#e0e0e0]" style={{ minHeight: 900 }}>
            <div className="p-8 space-y-5">
              {/* Header */}
              <div className="text-center space-y-2 pb-5 border-b border-[#f0f0f0]">
                <div className="h-4 bg-[#1c1d1d] rounded w-2/3 mx-auto" />
                <div className="h-3 bg-[#e0e0e0] rounded w-1/2 mx-auto mt-2" />
                <div className="h-3 bg-[#e8e8e8] rounded w-1/3 mx-auto" />
              </div>

              {/* Section heading */}
              <div className="h-4 bg-[#2a2a2a] rounded w-1/3" />

              {/* Normal paragraphs */}
              {[0,1].map(i => (
                <div key={i} className="space-y-2">
                  <div className="h-3 bg-[#e8e8e8] rounded w-full" />
                  <div className="h-3 bg-[#e8e8e8] rounded w-[92%]" />
                  <div className="h-3 bg-[#e8e8e8] rounded w-full" />
                  <div className="h-3 bg-[#e8e8e8] rounded w-[85%]" />
                </div>
              ))}

              {/* Evidence highlight (finding F1, page 12) */}
              {page === 12 && (
                <div className="relative border-l-4 border-orange-400 bg-orange-50 px-4 py-3 rounded-r-xl">
                  <div className="flex items-center gap-1.5 mb-2">
                    <AlertCircle className="size-3.5 text-orange-500" />
                    <span className="text-[11px] font-semibold text-orange-700">Evidence F1 · Criterion: Requirements analysis</span>
                    <button className="ml-auto text-[10px] text-orange-600 hover:underline font-medium">View finding</button>
                  </div>
                  <div className="space-y-1.5">
                    <div className="h-3 bg-orange-100 rounded w-full" />
                    <div className="h-3 bg-orange-100 rounded w-[88%]" />
                    <div className="h-3 bg-orange-100 rounded w-full" />
                  </div>
                </div>
              )}

              {/* Table mock */}
              <div className="border border-[#e0e0e0] rounded-lg overflow-hidden">
                <div className="bg-[#f8f8f8] px-3 py-2 flex gap-4 border-b border-[#e0e0e0]">
                  {["Use Case", "Actor", "Description"].map(h => (
                    <div key={h} className="h-3 bg-[#ccc] rounded flex-1" />
                  ))}
                </div>
                {[0,1,2,3].map(i => (
                  <div key={i} className="px-3 py-2.5 flex gap-4 border-b border-[#f0f0f0] last:border-0">
                    <div className="h-3 bg-[#e8e8e8] rounded flex-1" />
                    <div className="h-3 bg-[#e8e8e8] rounded flex-1" />
                    <div className="h-3 bg-[#e8e8e8] rounded flex-1" />
                  </div>
                ))}
              </div>

              {[0,1,2,3].map(i => (
                <div key={`b${i}`} className="space-y-2">
                  {i === 1 && <div className="h-4 bg-[#2a2a2a] rounded w-2/5" />}
                  <div className="h-3 bg-[#e8e8e8] rounded w-full" />
                  <div className="h-3 bg-[#e8e8e8] rounded w-[90%]" />
                  <div className="h-3 bg-[#e8e8e8] rounded w-full" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Review Panel */}
      <div className="w-[400px] flex-shrink-0 flex flex-col bg-white overflow-hidden border-l border-[#e7eae9]">
        {/* Summary Header */}
        <div className="flex-shrink-0 px-5 py-4 bg-[#f8f8f8] border-b border-[#e7eae9]">
          <div className="flex items-start justify-between mb-2.5">
            <div>
              <p className="text-[11px] text-[#85878d]">{submission.student} · v{submission.version}</p>
              <p className="text-sm font-bold text-[#1c1d1d]">{submission.assignment}</p>
            </div>
            <div className="text-right">
              <p className="text-2xl font-extrabold text-[#1c1d1d] leading-none">{totalScore.toFixed(1)}</p>
              <p className="text-[10px] text-[#85878d] mt-0.5">/ 10 suggested</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 text-[10px]">
            {saveState === "saved"  && <><CheckCircle className="size-3 text-green-500" /><span className="text-[#85878d]">Autosaved</span></>}
            {saveState === "saving" && <><RefreshCw   className="size-3 text-[#85878d] animate-spin" /><span className="text-[#85878d]">Saving...</span></>}
            {saveState === "error"  && <><XCircle     className="size-3 text-red-500" /><span className="text-red-600 font-medium">Unable to save</span></>}
          </div>
        </div>

        {/* Criteria List */}
        <div className="flex-1 overflow-y-auto">
          {CRITERIA.map((c) => {
            const sel    = selectedCrit === c.id;
            const state  = critStates[c.id];
            const cFinds = FINDINGS.filter(f => f.criterionId === c.id);
            return (
              <div key={c.id}>
                <button
                  className={clsx("w-full text-left px-5 py-3.5 border-b border-[#f5f5f5] hover:bg-[#fafafa] transition-colors",
                    sel && "bg-blue-50 border-blue-100"
                  )}
                  onClick={() => setSelectedCrit(sel ? null : c.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded-full",
                          state === "accepted" ? "bg-green-100 text-green-700" :
                          state === "rejected" ? "bg-red-100 text-red-700" :
                          "bg-[#f0f0f0] text-[#42404c]"
                        )}>
                          {state === "accepted" ? "✓ Accepted" : state === "rejected" ? "✗ Rejected" : "Pending review"}
                        </span>
                        <span className="text-[10px] text-[#85878d]">{c.weight}%</span>
                      </div>
                      <p className="text-xs font-semibold text-[#1c1d1d]">{c.name}</p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className="text-sm font-extrabold text-[#1c1d1d]">{scores[c.id]}<span className="text-[11px] font-normal text-[#85878d]">/{c.weight}</span></p>
                      <p className="text-[10px] text-[#85878d]">{Math.round(c.confidence * 100)}% confidence</p>
                    </div>
                  </div>
                  {cFinds.length > 0 && (
                    <div className="flex items-center gap-1 mt-1.5">
                      <AlertCircle className="size-3 text-orange-500" />
                      <span className="text-[10px] text-orange-600 font-medium">{cFinds.length} finding</span>
                    </div>
                  )}
                </button>

                {sel && crit && (
                  <div className="bg-white px-5 py-4 border-b border-[#e7eae9] space-y-4">
                    {/* Score */}
                    <div>
                      <p className="text-[10px] text-[#85878d] mb-2 font-medium uppercase tracking-wide">Score</p>
                      <div className="flex items-center gap-2">
                        <button onClick={() => { setScores(s => ({...s, [c.id]: Math.max(0, s[c.id]-1)})); save(); }}
                          className="size-6 flex items-center justify-center border border-[#e7eae9] rounded-lg text-[#42404c] hover:bg-[#f5f7f9]">
                          <Minus className="size-3" />
                        </button>
                        <span className="text-base font-extrabold text-[#1c1d1d] w-10 text-center">{scores[c.id]}</span>
                        <button onClick={() => { setScores(s => ({...s, [c.id]: Math.min(c.weight, s[c.id]+1)})); save(); }}
                          className="size-6 flex items-center justify-center border border-[#e7eae9] rounded-lg text-[#42404c] hover:bg-[#f5f7f9]">
                          <Plus className="size-3" />
                        </button>
                        <span className="text-[10px] text-[#85878d]">/ {c.weight} points</span>
                        {scores[c.id] !== c.suggestedScore && (
                          <span className="text-[10px] text-orange-600 ml-auto font-medium">Suggested: {c.suggestedScore}</span>
                        )}
                      </div>
                    </div>

                    {/* Findings */}
                    {findings.map((f) => (
                      <div key={f.id} className="border border-[#e7eae9] rounded-xl p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded-full",
                            f.severity === "critical" ? "bg-red-100 text-red-700" :
                            f.severity === "major"    ? "bg-orange-100 text-orange-700" :
                            "bg-yellow-50 text-yellow-700"
                          )}>
                            {f.severity === "critical" ? "Critical" : f.severity === "major" ? "Major" : "Minor"}
                          </span>
                          <span className="text-[10px] text-[#85878d]">Page {f.page}</span>
                          <button className="ml-auto text-[10px] text-blue-600 hover:underline font-medium" onClick={() => setPage(f.page)}>
                            Go to page →
                          </button>
                        </div>
                        <p className="text-xs text-[#1c1d1d]">{f.description}</p>
                        <div className="bg-[#f8f8f8] rounded-lg p-2.5">
                          <p className="text-[10px] text-[#85878d] mb-1 font-medium">Suggested fix</p>
                          <p className="text-xs text-[#42404c]">{f.suggestion}</p>
                        </div>
                      </div>
                    ))}

                    {/* Accept / Reject */}
                    <div className="flex gap-2">
                      <button onClick={() => accept(c.id)} className={clsx(
                        "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-semibold border transition-colors",
                        critStates[c.id] === "accepted"
                          ? "bg-green-600 text-white border-green-600"
                          : "border-green-500 text-green-700 hover:bg-green-50"
                      )}>
                        <Check className="size-3.5" /> Accept
                      </button>
                      <button onClick={() => reject(c.id)} className={clsx(
                        "flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-semibold border transition-colors",
                        critStates[c.id] === "rejected"
                          ? "bg-red-600 text-white border-red-600"
                          : "border-red-400 text-red-600 hover:bg-red-50"
                      )}>
                        <X className="size-3.5" /> Reject
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Action Bar */}
        <div className="flex-shrink-0 px-5 py-4 border-t border-[#e7eae9] bg-white space-y-2">
          <div className="flex gap-2">
            <button className="flex-1 py-2 text-xs font-semibold border border-[#e7eae9] rounded-xl text-[#42404c] hover:bg-[#f5f7f9]">
              Save draft
            </button>
            <button className="flex-1 py-2 text-xs font-semibold bg-[#1c1d1d] text-white rounded-xl hover:bg-[#333]">
              Approve
            </button>
          </div>
          <button className="w-full py-2.5 text-xs font-semibold bg-green-600 text-white rounded-xl hover:bg-green-700">
            Publish result to student
          </button>
          <p className="text-[10px] text-center text-[#85878d]">
            Approval and publishing are separate actions · Publishing requires confirmation
          </p>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// STUDENT VIEWS
// ============================================================

function StudentAssignments({ onUpload, onResults, onStatus }: {
  onUpload: () => void; onResults: () => void; onStatus: () => void;
}) {
  const list = [
    { course: "Công nghệ phần mềm", name: "Software Requirements Specification", deadline: "31/07/2024", status: "submitted" as const, submittedAt: "15/07/2024" },
    { course: "Thực tập doanh nghiệp", name: "Internship Report", deadline: "20/08/2024", status: "open" as const, submittedAt: null },
    { course: "Công nghệ phần mềm", name: "System Design Report", deadline: "28/06/2024", status: "published" as const, submittedAt: "25/06/2024" },
  ];
  return (
    <div className="p-6 space-y-4 max-w-[720px]">
      <h2 className="text-lg font-bold text-[#1c1d1d]">Assignments</h2>
      <div className="space-y-3">
        {list.map((a, i) => (
          <div key={i} className="bg-white border border-[#e7eae9] rounded-2xl p-5 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <p className="text-[10px] font-semibold text-[#85878d] mb-0.5">{a.course}</p>
                <h3 className="text-sm font-bold text-[#1c1d1d]">{a.name}</h3>
                <p className="text-[11px] text-[#85878d] mt-0.5">
                  Deadline: <span className="font-semibold text-[#42404c]">{a.deadline}</span>
                  {a.submittedAt && <> · Submitted: <span className="font-semibold text-[#42404c]">{a.submittedAt}</span></>}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {a.status === "open" && (
                  <button onClick={onUpload} className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-[#1c1d1d] rounded-xl hover:bg-[#333]">
                    <Upload className="size-3.5" /> Submit report
                  </button>
                )}
                {a.status === "submitted" && (
                  <button onClick={onStatus} className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold border border-[#e7eae9] text-[#42404c] rounded-xl hover:bg-[#f5f7f9]">
                    <Clock className="size-3.5" /> Track
                  </button>
                )}
                {a.status === "published" && (
                  <button onClick={onResults} className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-green-600 rounded-xl hover:bg-green-700">
                    <Star className="size-3.5" /> View results
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StudentUpload() {
  const [stage, setStage] = useState<"idle" | "uploading" | "checking" | "done" | "error">("idle");
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<{ name: string; size: number } | null>(null);

  const simulate = () => {
    setStage("uploading");
    setTimeout(() => setStage("checking"), 1400);
    setTimeout(() => setStage("done"), 2800);
  };

  return (
    <div className="p-6 max-w-[560px] space-y-4">
      <h2 className="text-lg font-bold text-[#1c1d1d]">Submit report</h2>

      <div className="bg-white border border-[#e7eae9] rounded-2xl p-4 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <p className="text-sm font-bold text-[#1c1d1d]">Software Requirements Specification</p>
        <p className="text-[11px] text-[#85878d] mt-0.5">Due: 31/07/2024 23:59 · PDF with a text layer · Maximum 50 MB</p>
      </div>

      {stage === "idle" && (
        <div
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) setFile({ name: f.name, size: f.size }); }}
          className={clsx("border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-default",
            dragOver ? "border-[#1c1d1d] bg-[#f5f7f9]" : "border-[#e0e0e0] bg-white hover:border-[#bbb]"
          )}
        >
          <div className="size-12 bg-[#f5f7f9] rounded-2xl border border-[#e7eae9] flex items-center justify-center mx-auto mb-4">
            <Upload className="size-6 text-[#42404c]" />
          </div>
          <p className="text-sm font-bold text-[#1c1d1d] mb-1">Drop your PDF here</p>
          <p className="text-xs text-[#85878d] mb-4">or</p>
          <label className="px-5 py-2.5 text-xs font-semibold bg-[#1c1d1d] text-white rounded-xl cursor-pointer hover:bg-[#333] inline-block">
            <input type="file" accept=".pdf" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) setFile({ name: f.name, size: f.size }); }} />
            Choose PDF
          </label>
        </div>
      )}

      {file && stage === "idle" && (
        <div className="bg-[#f8f8f8] border border-[#e7eae9] rounded-2xl p-4 flex items-center gap-3">
          <div className="size-10 bg-white border border-[#e7eae9] rounded-xl flex items-center justify-center flex-shrink-0">
            <FileText className="size-5 text-[#42404c]" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-[#1c1d1d] truncate">{file.name}</p>
            <p className="text-[10px] text-[#85878d]">{(file.size / 1024 / 1024).toFixed(2)} MB · PDF</p>
          </div>
          <button onClick={() => setFile(null)} className="text-[#85878d] hover:text-[#1c1d1d] p-1">
            <X className="size-4" />
          </button>
        </div>
      )}

      {(stage === "uploading" || stage === "checking") && (
        <div className="bg-white border border-[#e7eae9] rounded-2xl p-6 space-y-4 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
          <div className="flex items-center gap-3">
            <RefreshCw className="size-5 text-[#42404c] animate-spin flex-shrink-0" />
            <div>
              <p className="text-xs font-semibold text-[#1c1d1d]">
                {stage === "uploading" ? "Uploading..." : "Checking PDF..."}
              </p>
              <p className="text-[11px] text-[#85878d]">
                {stage === "uploading" ? "Keep this page open" : "Checking format and text layer"}
              </p>
            </div>
          </div>
          <div className="h-2 bg-[#e8e8e8] rounded-full overflow-hidden">
            <div className="h-full bg-[#1c1d1d] rounded-full transition-all duration-500"
              style={{ width: stage === "uploading" ? "45%" : "82%" }} />
          </div>
          <p className="text-[10px] text-[#85878d] text-right">{stage === "uploading" ? "45%" : "82%"}</p>
        </div>
      )}

      {stage === "done" && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-5 flex items-start gap-3">
          <CheckCircle className="size-6 text-green-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-green-800">Submission received</p>
            <p className="text-xs text-green-700 mt-1">Your report is queued for evaluation. You will be notified when the result is ready.</p>
            <button onClick={() => { setStage("idle"); setFile(null); }} className="mt-2.5 text-xs font-semibold text-green-700 hover:underline">
              Submit a new version
            </button>
          </div>
        </div>
      )}

      {stage === "error" && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-5 flex items-start gap-3">
          <XCircle className="size-6 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-red-800">Invalid PDF — no text layer</p>
            <p className="text-xs text-red-700 mt-1">This appears to be a scanned PDF and contains no extractable text. OCR is not supported.</p>
            <p className="text-xs text-red-700 mt-1.5 font-semibold">→ Export the document again from Word, LaTeX or Google Docs, then resubmit it.</p>
            <button onClick={() => setStage("idle")} className="mt-2.5 text-xs font-semibold text-red-700 hover:underline">Try again</button>
          </div>
        </div>
      )}

      {file && stage === "idle" && (
        <button onClick={simulate} className="w-full py-3 text-sm font-bold text-white bg-[#1c1d1d] rounded-2xl hover:bg-[#333] transition-colors">
          Confirm submission
        </button>
      )}

      <div className="flex gap-2">
        <button onClick={() => setStage("error")} className="flex-1 py-2 text-xs text-[#85878d] border border-dashed border-[#e0e0e0] rounded-xl hover:bg-[#f8f8f8]">
          Demo: scanned PDF error
        </button>
        <button onClick={() => { setFile({ name: "bao-cao-cnpm.pdf", size: 2400000 }); setStage("idle"); }} className="flex-1 py-2 text-xs text-[#85878d] border border-dashed border-[#e0e0e0] rounded-xl hover:bg-[#f8f8f8]">
          Demo: choose file
        </button>
      </div>
    </div>
  );
}

function StudentStatus() {
  const steps = [
    { label: "Received",         time: "15/07 14:32", done: true  },
    { label: "PDF checked",      time: "15/07 14:33", done: true  },
    { label: "Queued",           time: "15/07 14:35", done: true  },
    { label: "Evaluating",       time: null,           done: false, active: true },
    { label: "Needs review",     time: null,           done: false },
    { label: "Approved",         time: null,           done: false },
    { label: "Published",        time: null,           done: false },
  ];
  return (
    <div className="p-6 max-w-[500px] space-y-4">
      <h2 className="text-lg font-bold text-[#1c1d1d]">Submission status</h2>
      <div className="bg-white border border-[#e7eae9] rounded-2xl p-5 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <div className="mb-4 pb-4 border-b border-[#f5f5f5]">
          <p className="text-sm font-bold text-[#1c1d1d]">Software Requirements Specification — Version 1</p>
          <p className="text-[11px] text-[#85878d] mt-0.5">Updated: 15/07/2024 14:35 · Estimated processing time: 2–4 hours</p>
        </div>
        <div className="relative">
          <div className="absolute left-[15px] top-4 bottom-4 w-px bg-[#e8e8e8]" />
          <div className="space-y-5">
            {steps.map((s, i) => {
              const isActive = "active" in s && s.active;
              const isDone   = s.done;
              return (
                <div key={i} className="flex items-start gap-4">
                  <div className={clsx("size-8 rounded-full border-2 flex items-center justify-center flex-shrink-0 z-10 bg-white transition-all",
                    isDone   ? "border-[#1c1d1d] bg-[#1c1d1d]" :
                    isActive ? "border-[#1c1d1d]" :
                    "border-[#e0e0e0]"
                  )}>
                    {isDone ? <Check className="size-3.5 text-white" /> : (
                      <div className={clsx("size-2 rounded-full", isActive ? "bg-[#1c1d1d]" : "bg-[#ddd]")} />
                    )}
                  </div>
                  <div className="pt-1">
                    <p className={clsx("text-xs font-semibold", isDone || isActive ? "text-[#1c1d1d]" : "text-[#aaa]")}>
                      {s.label}
                      {isActive && (
                        <span className="ml-2 text-[10px] text-blue-500 font-normal animate-pulse">Processing...</span>
                      )}
                    </p>
                    {s.time && <p className="text-[10px] text-[#85878d] mt-0.5">{s.time}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <p className="text-[11px] text-center text-[#85878d]">You will be notified when the result is ready. You can leave this page.</p>
    </div>
  );
}

function StudentResults() {
  const [expandedId, setExpandedId] = useState<string | null>("C2");

  const publishedCriteria = [
    { id: "C1", name: "Document structure",    weight: 15, score: 13, feedback: "The report is well structured and includes all required sections." },
    { id: "C2", name: "Requirements analysis", weight: 25, score: 18, feedback: "The analysis is mostly complete but several exception scenarios are missing." },
    { id: "C3", name: "Use Case Diagram",       weight: 20, score: 14, feedback: "The diagram is missing a system boundary. Add it in the next version." },
    { id: "C4", name: "System design",          weight: 25, score: 22, feedback: "The architecture is clear, coherent and sufficiently documented." },
    { id: "C5", name: "Consistency",            weight: 15, score: 10, feedback: "Several terms are used inconsistently across the report." },
  ];

  const totalMax   = publishedCriteria.reduce((s, c) => s + c.weight, 0);
  const totalScore = (publishedCriteria.reduce((s, c) => s + c.score, 0) / totalMax) * 10;

  const pubFindings = [
    { criterionId: "C2", severity: "major" as const, page: 12, description: "The use-case table is missing the Payment System actor.", suggestion: "Add the actor and the payment-related use cases." },
    { criterionId: "C3", severity: "major" as const, page: 23, description: "The Use Case Diagram has no system boundary.", suggestion: "Add a system boundary around all internal use cases." },
    { criterionId: "C5", severity: "critical" as const, page: 31, description: "The terms user and customer are used interchangeably.", suggestion: "Use one term consistently or define the distinction." },
  ];

  return (
    <div className="p-6 max-w-[680px] space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-[#1c1d1d]">Evaluation result</h2>
          <p className="text-xs text-[#85878d] mt-0.5">Software Requirements Specification · Published: 16/07/2024</p>
        </div>
        <StatusBadge status="published" />
      </div>

      {/* Score card */}
      <div className="bg-white border border-[#e7eae9] rounded-2xl p-6 flex items-center gap-8 shadow-[0_0_8px_rgba(0,0,0,0.04)]">
        <div className="text-center flex-shrink-0">
          <p className="text-5xl font-extrabold text-[#1c1d1d] leading-none">{totalScore.toFixed(1)}</p>
          <p className="text-xs text-[#85878d] mt-1.5">/ 10 points</p>
        </div>
        <div className="flex-1 space-y-2.5">
          {publishedCriteria.map((c) => (
            <div key={c.id} className="flex items-center gap-3">
              <span className="text-[11px] text-[#42404c] w-36 flex-shrink-0 truncate font-medium">{c.name}</span>
              <div className="flex-1 h-2 bg-[#f0f0f0] rounded-full overflow-hidden">
                <div className="h-full bg-[#1c1d1d] rounded-full transition-all" style={{ width: `${(c.score / c.weight) * 100}%` }} />
              </div>
              <span className="text-[11px] font-bold text-[#1c1d1d] w-12 text-right flex-shrink-0">{c.score}/{c.weight}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Criteria detail */}
      <div className="space-y-2">
        <h3 className="text-sm font-bold text-[#1c1d1d]">Criterion breakdown</h3>
        {publishedCriteria.map((c) => {
          const pct = c.score / c.weight;
          return (
            <div key={c.id} className="bg-white border border-[#e7eae9] rounded-2xl overflow-hidden shadow-[0_0_4px_rgba(0,0,0,0.04)]">
              <button
                className="w-full flex items-center justify-between p-4 text-left hover:bg-[#fafafa] transition-colors"
                onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}
              >
                <div className="flex items-center gap-3">
                  <div className={clsx("size-9 rounded-full flex items-center justify-center text-xs font-extrabold border-2",
                    pct >= 0.8 ? "border-green-500 text-green-700" :
                    pct >= 0.6 ? "border-[#1c1d1d] text-[#1c1d1d]" :
                    "border-orange-400 text-orange-700"
                  )}>
                    {c.score}
                  </div>
                  <div>
                    <p className="text-xs font-bold text-[#1c1d1d]">{c.name}</p>
                    <p className="text-[10px] text-[#85878d]">{c.weight}% weight</p>
                  </div>
                </div>
                <ChevronDown className={clsx("size-4 text-[#85878d] transition-transform", expandedId === c.id && "rotate-180")} />
              </button>

              {expandedId === c.id && (
                <div className="px-5 pb-4 border-t border-[#f5f5f5] pt-3 space-y-3">
                  <div className="bg-[#f8f8f8] rounded-xl p-3.5 border border-[#f0f0f0]">
                    <p className="text-[10px] text-[#85878d] mb-1 font-semibold uppercase tracking-wide">Teacher feedback</p>
                    <p className="text-xs text-[#42404c]">{c.feedback}</p>
                  </div>
                  {pubFindings.filter(f => f.criterionId === c.id).map((f, fi) => (
                    <div key={fi} className={clsx("rounded-xl p-3.5 border text-xs space-y-2",
                      f.severity === "critical" ? "border-red-200 bg-red-50" :
                      f.severity === "major"    ? "border-orange-200 bg-orange-50" :
                      "border-yellow-200 bg-yellow-50"
                    )}>
                      <div className="flex items-center gap-2">
                        <span className={clsx("text-[10px] font-semibold px-1.5 py-0.5 rounded-full",
                          f.severity === "critical" ? "bg-red-200 text-red-800" :
                          f.severity === "major"    ? "bg-orange-200 text-orange-800" : "bg-yellow-200 text-yellow-800"
                        )}>
                          {f.severity === "critical" ? "Critical" : f.severity === "major" ? "Major" : "Minor"} · Page {f.page}
                        </span>
                      </div>
                      <p className="text-[#42404c]">{f.description}</p>
                      <p className="text-[#85878d]"><span className="font-semibold">Suggestion: </span>{f.suggestion}</p>
                    </div>
                  ))}
                  <button className="text-xs font-medium text-blue-600 hover:underline flex items-center gap-1.5">
                    <MessageSquare className="size-3.5" /> Request a review of this criterion
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================
// ROOT APP
// ============================================================

export default function App() {
  const [role, setRole] = useState<Role>("teacher");
  const [view, setView] = useState<View>("teacher-courses");
  const [courses, setCourses] = useState<Course[]>(INITIAL_COURSES);
  const [assignments, setAssignments] = useState<Assignment[]>(INITIAL_ASSIGNMENTS);
  const [selectedCourseId, setSelectedCourseId] = useState(INITIAL_COURSES[0].id);
  const [editingCourse, setEditingCourse] = useState<Course | null>(null);
  const [editingAssignment, setEditingAssignment] = useState<Assignment | null>(null);
  const [queueAssignmentId, setQueueAssignmentId] = useState(INITIAL_ASSIGNMENTS[0].id);
  const [selSub, setSelSub] = useState(SUBMISSIONS[0]);

  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? courses[0];
  const courseAssignments = assignments.filter((assignment) => assignment.courseId === selectedCourse?.id);
  const queueAssignment = assignments.find((assignment) => assignment.id === queueAssignmentId) ?? assignments[0];

  const handleRoleChange = (r: Role) => {
    setRole(r);
    if (r === "admin")   setView("admin-dashboard");
    if (r === "teacher") setView("teacher-courses");
    if (r === "student") setView("student-assignments");
  };

  const saveCourse = (course: Course) => {
    setCourses((current) => current.some((item) => item.id === course.id)
      ? current.map((item) => item.id === course.id ? course : item)
      : [...current, course]
    );
    setSelectedCourseId(course.id);
    setEditingCourse(null);
    setView("teacher-course");
  };

  const saveAssignment = (assignment: Assignment) => {
    setAssignments((current) => current.some((item) => item.id === assignment.id)
      ? current.map((item) => item.id === assignment.id ? assignment : item)
      : [...current, assignment]
    );
    setEditingAssignment(null);
    setView("teacher-course");
  };

  const isReview = view === "teacher-review";

  return (
    <div className="flex h-screen bg-white overflow-hidden" style={{ fontFamily: "'Inter', 'Roboto', system-ui, sans-serif" }}>
      <Sidebar role={role} view={view} onViewChange={setView} onRoleChange={handleRoleChange} />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopBar view={view} />

        <main className={clsx("flex-1 bg-[#fafafa]", isReview ? "overflow-hidden" : "overflow-auto")}>
          {view === "admin-dashboard"     && <AdminDashboard />}
          {view === "admin-users"         && <AdminUsers />}
          {view === "admin-jobs"          && <AdminJobs />}
          {view === "admin-audit"         && <AdminAuditLog />}
          {view === "teacher-courses" && (
            <CourseCatalog
              courses={courses}
              assignments={assignments}
              onCreate={() => { setEditingCourse(null); setView("teacher-course-editor"); }}
              onSelect={(course) => { setSelectedCourseId(course.id); setView("teacher-course"); }}
            />
          )}
          {view === "teacher-course" && selectedCourse && (
            <CourseWorkspace
              course={selectedCourse}
              assignments={courseAssignments}
              onBack={() => setView("teacher-courses")}
              onEditCourse={() => { setEditingCourse(selectedCourse); setView("teacher-course-editor"); }}
              onCreateAssignment={() => { setEditingAssignment(null); setView("teacher-assignment-editor"); }}
              onEditAssignment={(assignment) => { setEditingAssignment(assignment); setView("teacher-assignment-editor"); }}
              onQueue={(assignment) => { setQueueAssignmentId(assignment.id); setView("teacher-queue"); }}
            />
          )}
          {view === "teacher-course-editor" && (
            <CourseEditor
              course={editingCourse}
              onBack={() => setView(editingCourse ? "teacher-course" : "teacher-courses")}
              onSave={saveCourse}
            />
          )}
          {view === "teacher-assignment-editor" && selectedCourse && (
            <AssignmentEditor
              key={editingAssignment?.id ?? `new-${selectedCourse.id}`}
              course={selectedCourse}
              assignment={editingAssignment}
              onBack={() => setView("teacher-course")}
              onSave={saveAssignment}
            />
          )}
          {view === "teacher-queue" && (
            <SubmissionQueue assignmentName={queueAssignment?.title ?? "All assignments"} onSelect={sub => { setSelSub(sub); setView("teacher-review"); }} />
          )}
          {view === "teacher-review" && (
            <ReviewWorkspace submission={selSub} onBack={() => setView("teacher-queue")} />
          )}
          {view === "student-assignments" && (
            <StudentAssignments
              onUpload={() => setView("student-upload")}
              onResults={() => setView("student-results")}
              onStatus={() => setView("student-status")}
            />
          )}
          {view === "student-upload"  && <StudentUpload />}
          {view === "student-status"  && <StudentStatus />}
          {view === "student-results" && <StudentResults />}
        </main>
      </div>
    </div>
  );
}
