import React, { useState } from 'react';
import { Activity, RotateCcw, AlertTriangle, CheckCircle2, Clock, Terminal } from 'lucide-react';
import { EvaluationJob } from '../../types/docgrading';

interface JobMonitoringViewProps {
  jobs: EvaluationJob[];
  onRetryJob: (jobId: string) => void;
}

export const JobMonitoringView: React.FC<JobMonitoringViewProps> = ({ jobs, onRetryJob }) => {
  const [selectedJob, setSelectedJob] = useState<EvaluationJob | null>(null);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900">Giám sát Hàng đợi Xử lý Celery & Worker</h1>
        <p className="text-xs text-slate-500 mt-1">
          Theo dõi các tiến trình trích xuất Document IR, đánh giá 12 tiêu chí SRS và quản lý các tác vụ lỗi.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
              <tr>
                <th className="px-4 py-3">Job ID & Correlation ID</th>
                <th className="px-4 py-3">Bài nộp & Sinh viên</th>
                <th className="px-4 py-3">Bộ đánh giá (Evaluator)</th>
                <th className="px-4 py-3">Thời gian xử lý</th>
                <th className="px-4 py-3">Trạng thái</th>
                <th className="px-4 py-3 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((job) => (
                <tr key={job.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-3.5">
                    <div className="font-mono font-bold text-slate-900">{job.id}</div>
                    <div className="text-[10px] text-slate-400 font-mono">cid: {job.correlationId}</div>
                  </td>
                  <td className="px-4 py-3.5">
                    <div className="font-semibold text-slate-900">{job.studentName}</div>
                    <div className="text-[11px] text-slate-500 truncate max-w-xs">{job.assignmentTitle}</div>
                  </td>
                  <td className="px-4 py-3.5 font-mono text-slate-600 text-[11px]">{job.evaluator}</td>
                  <td className="px-4 py-3.5 font-mono text-slate-600">{job.duration}</td>
                  <td className="px-4 py-3.5">
                    {job.status === 'completed' ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Thành công (100%)</span>
                      </span>
                    ) : job.status === 'failed' ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
                        <AlertTriangle className="w-3 h-3" />
                        <span>Lỗi phân tích</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200">
                        <Clock className="w-3 h-3" />
                        <span>Đang xử lý</span>
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3.5 text-right space-x-2">
                    {job.status === 'failed' && (
                      <button
                        type="button"
                        onClick={() => onRetryJob(job.id)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 bg-slate-900 text-white rounded-md text-[11px] font-medium hover:bg-slate-800"
                      >
                        <RotateCcw className="w-3 h-3" />
                        <span>Thử lại (Retry)</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setSelectedJob(job)}
                      className="px-2.5 py-1 border border-slate-200 rounded-md text-[11px] text-slate-600 hover:bg-slate-100"
                    >
                      Chi tiết log
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Log Detail Modal */}
      {selectedJob && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-lg p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-sky-600" />
                <h3 className="font-bold text-sm text-slate-900">Chi tiết tác vụ: {selectedJob.id}</h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedJob(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            <div className="space-y-2 bg-slate-900 text-slate-200 p-4 rounded-xl font-mono text-[11px] leading-relaxed max-h-60 overflow-y-auto">
              <p className="text-sky-400">[INFO] Worker node: celery@worker-node-01.local</p>
              <p>[INFO] Task name: docgrading.tasks.evaluate_srs_rubric</p>
              <p>[INFO] Correlation ID: {selectedJob.correlationId}</p>
              <p>[INFO] Evaluator pipeline: {selectedJob.evaluator}</p>
              {selectedJob.errorReason ? (
                <p className="text-rose-400 mt-2 font-bold">[ERROR] {selectedJob.errorReason}</p>
              ) : (
                <p className="text-emerald-400 mt-2">[SUCCESS] All 12 criteria analyzed without error.</p>
              )}
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="button"
                onClick={() => setSelectedJob(null)}
                className="px-4 py-1.5 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800"
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
