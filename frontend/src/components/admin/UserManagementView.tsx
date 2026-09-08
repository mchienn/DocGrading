import React, { useState } from 'react';
import { Users, Search, Shield, GraduationCap, UserCheck, Lock, Unlock } from 'lucide-react';
import { AppUser, UserRole } from '../../types/docgrading';

interface UserManagementViewProps {
  users: AppUser[];
  onUpdateUserRole: (userId: string, newRole: UserRole) => void;
  onToggleUserLock: (userId: string) => void;
}

export const UserManagementView: React.FC<UserManagementViewProps> = ({
  users,
  onUpdateUserRole,
  onToggleUserLock,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('all');

  const filtered = users.filter((u) => {
    if (roleFilter !== 'all' && u.role !== roleFilter) return false;
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      return (
        u.fullName.toLowerCase().includes(term) ||
        u.email.toLowerCase().includes(term) ||
        u.department.toLowerCase().includes(term)
      );
    }
    return true;
  });

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="border-b border-slate-200 pb-5">
        <h1 className="text-xl font-bold text-slate-900">Quản lý Người dùng & Phân quyền (RBAC)</h1>
        <p className="text-xs text-slate-500 mt-1">
          Hệ thống tài khoản đóng do Admin khởi tạo. Hỗ trợ 3 vai trò: Quản trị viên, Giảng viên bộ môn và Sinh viên.
        </p>
      </div>

      {/* Filter and Search */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
        <div className="relative flex-1 max-w-sm">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Tìm theo họ tên, email hoặc đơn vị..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-xs focus:outline-hidden focus:ring-1 focus:ring-sky-500"
          />
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500 font-medium">Lọc vai trò:</span>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white text-slate-800 focus:outline-hidden focus:ring-1 focus:ring-sky-500"
          >
            <option value="all">Tất cả vai trò</option>
            <option value="teacher">Giảng viên (Teacher)</option>
            <option value="student">Sinh viên (Student)</option>
            <option value="admin">Quản trị viên (Admin)</option>
          </select>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-medium">
              <tr>
                <th className="px-4 py-3">Họ tên & Email</th>
                <th className="px-4 py-3">Khoa / Bộ môn</th>
                <th className="px-4 py-3">Vai trò hiện tại</th>
                <th className="px-4 py-3">Trạng thái</th>
                <th className="px-4 py-3 text-right">Thao tác quyền</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((user) => (
                <tr key={user.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-4 py-3.5">
                    <div className="font-semibold text-slate-900">{user.fullName}</div>
                    <div className="text-[11px] text-slate-400 font-mono">{user.email}</div>
                  </td>
                  <td className="px-4 py-3.5 text-slate-600">{user.department}</td>
                  <td className="px-4 py-3.5">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold border ${
                        user.role === 'admin'
                          ? 'bg-amber-50 text-amber-700 border-amber-200'
                          : user.role === 'teacher'
                          ? 'bg-sky-50 text-sky-700 border-sky-200'
                          : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      }`}
                    >
                      {user.role === 'admin' && <Shield className="w-3 h-3" />}
                      {user.role === 'teacher' && <GraduationCap className="w-3 h-3" />}
                      {user.role === 'student' && <UserCheck className="w-3 h-3" />}
                      <span className="capitalize">{user.role}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3.5">
                    {user.status === 'active' ? (
                      <span className="text-emerald-600 font-medium">Hoạt động</span>
                    ) : (
                      <span className="text-rose-600 font-medium">Đã khóa</span>
                    )}
                  </td>
                  <td className="px-4 py-3.5 text-right space-x-2">
                    <select
                      value={user.role}
                      onChange={(e) => onUpdateUserRole(user.id, e.target.value as UserRole)}
                      className="px-2 py-1 border border-slate-200 rounded text-xs bg-white text-slate-700 focus:outline-hidden"
                    >
                      <option value="student">Đổi sang Sinh viên</option>
                      <option value="teacher">Đổi sang Giảng viên</option>
                      <option value="admin">Đổi sang Admin</option>
                    </select>

                    <button
                      type="button"
                      onClick={() => onToggleUserLock(user.id)}
                      className="p-1 rounded hover:bg-slate-100 text-slate-500"
                      title={user.status === 'active' ? 'Khóa tài khoản' : 'Mở khóa tài khoản'}
                    >
                      {user.status === 'active' ? (
                        <Lock className="w-3.5 h-3.5 text-slate-400" />
                      ) : (
                        <Unlock className="w-3.5 h-3.5 text-emerald-600" />
                      )}
                    </button>
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
