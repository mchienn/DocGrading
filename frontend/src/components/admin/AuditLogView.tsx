import React, { useEffect, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, apiData, getErrorMessage } from '../../api/client';

export const AuditLogView: React.FC = () => {
  const [filters, setFilters] = useState<{ resource_type?: string; actor_user_id?: string; from_time?: string; to_time?: string }>({});
  const [page, setPage] = useState(1);
  const [filterError, setFilterError] = useState<string>();
  const [actorSearch, setActorSearch] = useState('');
  const [actorUserId, setActorUserId] = useState('');
  const [debouncedActorSearch, setDebouncedActorSearch] = useState('');
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedActorSearch(actorSearch.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [actorSearch]);
  const logs = useQuery({
    queryKey: ['admin-audit', filters, page],
    queryFn: () => apiData(api.GET('/api/v1/operations/audit-events', { params: { query: { ...filters, page, page_size: 25 } } })),
  });
  const usersQuery = useQuery({
    queryKey: ['admin-audit-users', debouncedActorSearch],
    queryFn: () => apiData(api.GET('/api/v1/users', {
      params: {
        query: {
          search: debouncedActorSearch || undefined,
          page: 1,
          page_size: 100,
        },
      },
    })),
    placeholderData: keepPreviousData,
  });
  const applyFilters = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const from = String(fields.get('from_time') || '');
    const to = String(fields.get('to_time') || '');
    if (from && to && new Date(from) > new Date(to)) { setFilterError('From time must not be after to time.'); return; }
    setFilterError(undefined);
    setFilters({
      resource_type: String(fields.get('resource_type')).trim() || undefined,
      actor_user_id: String(fields.get('actor_user_id')).trim() || undefined,
      from_time: from ? new Date(from).toISOString() : undefined,
      to_time: to ? new Date(to).toISOString() : undefined,
    });
    setPage(1);
  };
  const pages = Math.max(1, Math.ceil((logs.data?.total ?? 0) / 25));
  return <div className="p-6 sm:p-8 max-w-7xl mx-auto space-y-6">
    <h1 className="text-2xl font-bold border-b border-slate-200 pb-5">Audit trail</h1>
    <form onSubmit={applyFilters} aria-label="Audit filters" className="flex flex-wrap gap-4 p-4 bg-white border border-slate-200 rounded-xl">
      <label className="text-sm">Resource type<input name="resource_type" maxLength={128} placeholder="e.g. User" className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg" /></label>
      <label className="text-sm">
        Find actor
        <input
          value={actorSearch}
          onChange={(event) => {
            setActorSearch(event.target.value);
            setActorUserId('');
          }}
          placeholder="Name or email"
          className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg"
        />
      </label>
      <label className="text-sm">
        Actor
        <select
          name="actor_user_id"
          value={actorUserId}
          onChange={(event) => setActorUserId(event.target.value)}
          className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg bg-white text-sm"
        >
          <option value="">All actors</option>
          {usersQuery.data?.items.map((user) => (
            <option key={user.id} value={user.id}>{user.display_name} ({user.email})</option>
          ))}
        </select>
      </label>
      <label className="text-sm">From (local time)<input name="from_time" type="datetime-local" className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg" /></label>
      <label className="text-sm">To (local time)<input name="to_time" type="datetime-local" className="block mt-1 px-3 py-2 border border-slate-200 rounded-lg" /></label>
      <button type="submit" className="self-end px-3 py-2 bg-[#1F4B7A] text-white rounded-lg">Apply filters</button>
      <button type="reset" onClick={() => {
        setFilters({});
        setActorSearch('');
        setActorUserId('');
        setPage(1);
        setFilterError(undefined);
      }} className="self-end px-3 py-2 border border-slate-200 rounded-lg">Clear</button>
      <button type="button" disabled={logs.isFetching} onClick={() => void logs.refetch()} className="self-end px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Refresh</button>
    </form>
    {(filterError || logs.error || usersQuery.error) && <p role="alert" className="text-rose-700">{filterError ?? getErrorMessage(logs.error ?? usersQuery.error)}</p>}
    {logs.isLoading && <p role="status">Loading audit events...</p>}
    <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto">
      <table className="w-full text-sm text-left">
        <thead className="bg-slate-50">
          <tr>
            {['Time', 'Actor', 'Action / Resource', 'Reason'].map((label) => (
              <th key={label} className="p-4">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {logs.data?.items.map((log) => {
            return (
              <tr key={log.id} className="border-t border-slate-200 align-top">
                <td className="p-4 whitespace-nowrap">{new Date(log.occurred_at).toLocaleString()}</td>
                <td className="p-4">
                  {log.actor_display_name ? (
                    <div>
                      <div className="font-semibold text-slate-900">{log.actor_display_name}</div>
                      {log.actor_email && <div className="text-xs text-slate-500">{log.actor_email}</div>}
                    </div>
                  ) : (
                    <div className="font-medium text-slate-700">
                      {log.actor_type === 'SYSTEM' ? 'System' : log.actor_type}
                    </div>
                  )}
                </td>
                <td className="p-4">
                  <p className="font-semibold text-slate-900">{log.action} · {log.resource_type}</p>
                  <details className="mt-1">
                    <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-700 select-none">
                      Technical details
                    </summary>
                    <div className="mt-1 p-2 bg-slate-50 rounded text-xs space-y-1 font-mono text-slate-600 break-all">
                      <div>Event ID: {log.id}</div>
                      <div>Resource ID: {log.resource_id}</div>
                      {log.actor_user_id && <div>Actor ID: {log.actor_user_id}</div>}
                      {log.before && (
                        <div className="pt-2">
                          <div className="font-sans font-semibold text-slate-700">Before</div>
                          <pre className="whitespace-pre-wrap break-all">{JSON.stringify(log.before, null, 2)}</pre>
                        </div>
                      )}
                      {log.after && (
                        <div className="pt-2">
                          <div className="font-sans font-semibold text-slate-700">After</div>
                          <pre className="whitespace-pre-wrap break-all">{JSON.stringify(log.after, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  </details>
                </td>
                <td className="p-4 max-w-lg">
                  <p className="break-words text-slate-800">{log.reason}</p>
                </td>
              </tr>
            );
          })}
          {logs.data?.items.length === 0 && (
            <tr><td colSpan={4} className="p-8 text-center text-slate-500">No audit events match these filters.</td></tr>
          )}
        </tbody>
      </table>
    </div>
    <div className="flex justify-between text-sm"><span>{logs.data?.total ?? '—'} events · page {page} of {pages}</span><div className="flex gap-2"><button type="button" aria-label="Previous page" disabled={page <= 1 || logs.isFetching} onClick={() => setPage(page - 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Previous</button><button type="button" aria-label="Next page" disabled={page >= pages || logs.isFetching} onClick={() => setPage(page + 1)} className="px-3 py-2 border border-slate-200 rounded-lg disabled:opacity-40">Next</button></div></div>
  </div>;
};
