import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type AdminUser = components['schemas']['AdminUserResponse'];
type UserRole = components['schemas']['UserRole'];
type UserStatus = components['schemas']['UserStatus'];
const roles: UserRole[] = ['ADMIN', 'TEACHER', 'STUDENT'];
const inputClass = 'block mt-1 w-full px-3 py-2 border border-slate-300 rounded-lg';

const UserForm: React.FC<{ user: AdminUser | null; currentUserId: string; onClose: () => void }> = ({ user, currentUserId, onClose }) => {
  const dialog = useRef<HTMLDialogElement>(null);
  const queryClient = useQueryClient();
  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>(user?.roles ?? ['STUDENT']);
  const [status, setStatus] = useState<UserStatus>(user?.status ?? 'ACTIVE');
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const isSelf = user?.id === currentUserId;
  useEffect(() => { dialog.current?.showModal(); }, []);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setError(undefined);
    if (!selectedRoles.length) { setError('Select at least one role.'); return; }
    setSaving(true);
    try {
      if (user) {
        const reason = String(fields.get('reason')).trim();
        if (!reason) { setError('A reason is required.'); return; }
        await apiData(api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: user.id } }, body: { roles: selectedRoles, status, reason } }));
      } else {
        await apiData(api.POST('/api/v1/users', { body: {
          email: String(fields.get('email')).trim().toLowerCase(),
          display_name: String(fields.get('display_name')).trim(),
          password: String(fields.get('password')),
          roles: selectedRoles,
        } }));
      }
      form.reset();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
      onClose();
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      // Keep plaintext out of query/mutation caches and clear the input after a request.
      const password = form.elements.namedItem('password');
      if (password instanceof HTMLInputElement) password.value = '';
      setSaving(false);
    }
  };

  return <dialog ref={dialog} aria-labelledby="user-form-title" onCancel={(event) => { if (saving) event.preventDefault(); }} onClose={onClose} className="m-auto w-full max-w-md rounded-xl border border-slate-200 p-5 backdrop:bg-slate-900/50">
    <form onSubmit={submit} className="space-y-4">
      <h2 id="user-form-title" className="font-bold text-lg">{user ? `Edit ${user.display_name}` : 'Create user'}</h2>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      <fieldset disabled={saving} className="space-y-4">
        {!user && <>
          <label className="block text-sm">Email<input autoFocus required name="email" type="email" maxLength={320} autoComplete="off" className={inputClass} /></label>
          <label className="block text-sm">Display name<input required name="display_name" maxLength={255} className={inputClass} /></label>
          <label className="block text-sm">Password (12–512 characters)<input required name="password" type="password" minLength={12} maxLength={512} autoComplete="new-password" className={inputClass} /></label>
          <p className="text-xs text-slate-500">New accounts start ACTIVE.</p>
        </>}
        <fieldset className="space-y-2"><legend className="text-sm font-semibold">Roles</legend>
          {roles.map((role) => <label key={role} className="flex gap-2 text-sm"><input type="checkbox" checked={selectedRoles.includes(role)} disabled={isSelf && role === 'ADMIN'} onChange={(event) => setSelectedRoles(event.target.checked ? [...selectedRoles, role] : selectedRoles.filter((value) => value !== role))} />{role}</label>)}
        </fieldset>
        {user && <>
          <label className="block text-sm">Status<select value={status} disabled={isSelf} onChange={(event) => setStatus(event.target.value as UserStatus)} className={inputClass}><option>ACTIVE</option><option>LOCKED</option></select></label>
          <label className="block text-sm">Reason<textarea required name="reason" maxLength={1000} className={inputClass} /></label>
          {isSelf && <p className="text-xs text-slate-500">Your own account must remain active with the ADMIN role.</p>}
        </>}
      </fieldset>
      <div className="flex justify-end gap-2"><button type="button" disabled={saving} onClick={onClose} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Cancel</button><button disabled={saving} className="px-4 py-2 bg-[#1F4B7A] text-white rounded-lg disabled:opacity-40">{saving ? 'Saving...' : 'Save'}</button></div>
    </form>
  </dialog>;
};

export const UserManagementView: React.FC<{ currentUserId: string }> = ({ currentUserId }) => {
  const [search, setSearch] = useState('');
  const [role, setRole] = useState<UserRole | ''>('');
  const [status, setStatus] = useState<UserStatus | ''>('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<AdminUser | null | undefined>();
  const users = useQuery({
    queryKey: ['admin-users', search, role, status, page],
    queryFn: () => apiData(api.GET('/api/v1/users', { params: { query: { search: search.trim() || undefined, role: role || undefined, status: status || undefined, page, page_size: 25 } } })),
  });
  const pages = Math.max(1, Math.ceil((users.data?.total ?? 0) / 25));
  return <div className="p-6 sm:p-8 max-w-6xl mx-auto space-y-6">
    <div className="flex justify-between border-b border-slate-200 pb-5"><h1 className="text-2xl font-bold">Users</h1><button type="button" onClick={() => setEditing(null)} className="px-4 py-2 bg-[#1F4B7A] text-white rounded-lg">Create user</button></div>
    <section aria-label="User filters" className="flex flex-wrap gap-4 p-4 bg-white border border-slate-200 rounded-xl">
      <label className="text-sm">Search name or email<input value={search} maxLength={320} onChange={(event) => { setSearch(event.target.value); setPage(1); }} className={inputClass} /></label>
      <label className="text-sm">Role<select value={role} onChange={(event) => { setRole(event.target.value as UserRole | ''); setPage(1); }} className={inputClass}><option value="">ALL</option>{roles.map((value) => <option key={value}>{value}</option>)}</select></label>
      <label className="text-sm">Status<select value={status} onChange={(event) => { setStatus(event.target.value as UserStatus | ''); setPage(1); }} className={inputClass}><option value="">ALL</option><option>ACTIVE</option><option>LOCKED</option></select></label>
      <button type="button" disabled={users.isFetching} onClick={() => void users.refetch()} className="self-end px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Refresh</button>
    </section>
    {users.error && <p role="alert" className="text-rose-700">{getErrorMessage(users.error)}</p>}
    {users.isLoading && <p role="status">Loading users...</p>}
    <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto"><table className="w-full text-left text-sm"><thead className="bg-slate-50"><tr>{['Name / Email', 'Roles', 'Status', 'Actions'].map((label) => <th key={label} className="p-4">{label}</th>)}</tr></thead><tbody>
      {users.data?.items.map((user) => <tr key={user.id} className="border-t border-slate-200"><td className="p-4"><p className="font-semibold">{user.display_name}</p><p className="text-xs text-slate-500">{user.email}</p></td><td className="p-4">{user.roles.join(', ')}</td><td className="p-4">{user.status}</td><td className="p-4"><button type="button" onClick={() => setEditing(user)} className="px-3 py-2 border border-slate-200 rounded-lg">Edit roles / status</button></td></tr>)}
      {users.data?.items.length === 0 && <tr><td colSpan={4} className="p-8 text-center text-slate-500">No users match these filters.</td></tr>}
    </tbody></table></div>
    <div className="flex justify-between text-sm"><span>{users.data?.total ?? '—'} users · page {page} of {pages}</span><div className="flex gap-2"><button type="button" aria-label="Previous page" disabled={page <= 1 || users.isFetching} onClick={() => setPage(page - 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Previous</button><button type="button" aria-label="Next page" disabled={page >= pages || users.isFetching} onClick={() => setPage(page + 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Next</button></div></div>
    {editing !== undefined && <UserForm user={editing} currentUserId={currentUserId} onClose={() => setEditing(undefined)} />}
  </div>;
};
