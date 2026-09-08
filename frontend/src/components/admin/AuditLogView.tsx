import React, { useState } from 'react';
import { ShieldAlert, Search, Filter } from 'lucide-react';
import { AuditLogItem } from '../../types/docgrading';

interface AuditLogViewProps {
  logs: AuditLogItem[];
}

export const AuditLogView: React.FC<AuditLogViewProps> = ({ logs }) => {
  const [searchTerm, setSearchTerm] = useState('');

  const filtered = logs.filter((log) => {
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      return (
        log.userName.toLowerCase().includes(term) ||
        log.details.toLowerCase().includes(term) ||
        log.action.toLowerCase().includes(term)
      );
    }
    return true;
  });

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900">Nhật ký Kiểm toán Hệ thống (Audit Trail)</h1>
        <p className="text-xs text-slate-500 mt-1">
          Ghi nhận toàn bộ thao tác duyệt điểm, can thiệp điều chỉnh (override), công bố kết quả và thay đổi cấu hình.
        </p>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <input
            type="text"
            placeholder="Tìm kiếm nhật ký..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-72 px-3 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-hidden focus:ring-1 focus:ring-sky-500"
          />
          <span className="text-xs text-slate-400 font-mono">Lưu trữ tối thiểu: 365 ngày</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
              <tr>
                <th className="px-4 py-3">Thời gian</th>
                <th className="px-4 py-3">Người thực hiện</th>
                <th className="px-4 py-3">Loại hành động</th>
                <th className="px-4 py-3">Đối tượng tác động</th>
                <th className="px-4 py-3">Chi tiết & Căn cứ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((log) => (
                <tr key={log.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-3.5 font-mono text-slate-500 whitespace-nowrap">
                    {log.timestamp}
                  </td>
                  <td className="px-4 py-3.5 font-medium text-slate-900">{log.userName}</td>
                  <td className="px-4 py-3.5">
                    <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
                      {log.action}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 font-mono text-slate-600 text-[11px]">
                    {log.targetType} ({log.targetId})
                  </td>
                  <td className="px-4 py-3.5 text-slate-700 max-w-md leading-relaxed">
                    {log.details}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
