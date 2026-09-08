import React from 'react';
import {
  Users,
  Layers,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Server,
  ShieldAlert,
  ArrowUpRight,
  Database,
} from 'lucide-react';
import { EvaluationJob, AuditLogItem } from '../../types/docgrading';

interface AdminDashboardViewProps {
  jobs: EvaluationJob[];
  auditLogs: AuditLogItem[];
  onOpenJobs: () => void;
  onOpenUsers: () => void;
  onOpenAudit: () => void;
}

export const AdminDashboardView: React.FC<AdminDashboardViewProps> = ({
  jobs,
  auditLogs,
  onOpenJobs,
  onOpenUsers,
  onOpenAudit,
}) => {
  const completedJobs = jobs.filter((j) => j.status === 'completed').length;
  const failedJobs = jobs.filter((j) => j.status === 'failed').length;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="border-b border-slate-200 pb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Bảng điều khiển Quản trị Hệ thống (Admin)</h1>
          <p className="text-xs text-slate-500 mt-1">
            Giám sát vận hành cụm worker Celery, hàng đợi đánh giá PDF, người dùng và nhật ký kiểm toán.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="font-semibold text-slate-700">Production Node: Active</span>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span>Tổng người dùng</span>
            <Users className="w-4 h-4 text-slate-500" />
          </div>
          <p className="text-2xl font-bold text-slate-900 font-mono">138</p>
          <span className="text-[11px] text-slate-500">12 Giảng viên • 124 Sinh viên • 2 Admin</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span>Hàng đợi Celery</span>
            <Activity className="w-4 h-4 text-sky-500" />
          </div>
          <p className="text-2xl font-bold text-slate-900 font-mono">0 task</p>
          <span className="text-[11px] text-emerald-600 font-medium">Hàng đợi thông suốt (Queue depth: 0)</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span>Thời gian xử lý TB</span>
            <Clock className="w-4 h-4 text-slate-500" />
          </div>
          <p className="text-2xl font-bold text-slate-900 font-mono">38.2s</p>
          <span className="text-[11px] text-slate-500">Bao gồm trích xuất IR & 12 tiêu chí</span>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-2">
          <div className="flex items-center justify-between text-slate-400">
            <span>Tỷ lệ phân tích thành công</span>
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          </div>
          <p className="text-2xl font-bold text-emerald-600 font-mono">96.8%</p>
          <span className="text-[11px] text-slate-500">Chỉ từ chối khi PDF scan không text</span>
        </div>
      </div>

      {/* 2-column details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Jobs */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-2xs p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-sm font-bold text-slate-900">Trạng thái các Job đánh giá gần đây</h2>
            <button
              type="button"
              onClick={onOpenJobs}
              className="text-xs text-sky-600 hover:underline flex items-center gap-1 font-medium"
            >
              <span>Xem tất cả</span>
              <ArrowUpRight className="w-3 h-3" />
            </button>
          </div>

          <div className="space-y-2.5 text-xs">
            {jobs.map((job) => (
              <div
                key={job.id}
                className="p-3 bg-slate-50 rounded-lg border border-slate-200 flex items-center justify-between gap-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-slate-800">{job.id}</span>
                    <span className="font-semibold text-slate-900 truncate max-w-xs">
                      {job.studentName}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-0.5">{job.evaluator}</p>
                </div>

                <div className="text-right shrink-0">
                  {job.status === 'completed' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-50 text-emerald-700 font-mono">
                      <CheckCircle2 className="w-3 h-3" />
                      {job.duration}
                    </span>
                  ) : job.status === 'failed' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-rose-50 text-rose-700">
                      <AlertTriangle className="w-3 h-3" />
                      Lỗi Scan PDF
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-sky-50 text-sky-700">
                      Đang chạy
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Audit Log Highlights */}
        <div className="bg-white rounded-xl border border-slate-200 shadow-2xs p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <h2 className="text-sm font-bold text-slate-900">Lịch sử Audit Log gần nhất</h2>
            <button
              type="button"
              onClick={onOpenAudit}
              className="text-xs text-sky-600 hover:underline flex items-center gap-1 font-medium"
            >
              <span>Xem nhật ký</span>
              <ArrowUpRight className="w-3 h-3" />
            </button>
          </div>

          <div className="space-y-3 text-xs">
            {auditLogs.slice(0, 4).map((log) => (
              <div key={log.id} className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
                  <span className="font-semibold text-slate-700">{log.userName}</span>
                  <span className="font-mono">{log.timestamp}</span>
                </div>
                <p className="text-slate-800 text-xs leading-relaxed">{log.details}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
