import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Download,
  FileText,
  Search,
  X,
  Loader2,
  RefreshCw,
  FolderOpen,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';
import type { WorkspaceRole } from '../../types/api';
import { AccountNav } from './AccountNav';

type DocumentStatus = components['schemas']['DocumentStatus'];
type DocumentVersionItem = components['schemas']['DocumentVersionListItem'];

const documentStatuses: DocumentStatus[] = [
  'UPLOADING',
  'VALIDATING',
  'INVALID',
  'QUEUED',
  'PROCESSING',
  'AWAITING_REVIEW',
  'APPROVED',
  'PUBLISHED',
  'PROCESSING_FAILED',
];

interface AccountFilesViewProps {
  activeRole: WorkspaceRole;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getStatusBadge(status: DocumentStatus): { bg: string; text: string; border: string } {
  switch (status) {
    case 'PUBLISHED':
    case 'APPROVED':
      return { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' };
    case 'AWAITING_REVIEW':
      return { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' };
    case 'INVALID':
    case 'PROCESSING_FAILED':
      return { bg: 'bg-rose-50', text: 'text-rose-700', border: 'border-rose-200' };
    case 'PROCESSING':
    case 'VALIDATING':
    case 'QUEUED':
      return { bg: 'bg-sky-50', text: 'text-sky-700', border: 'border-sky-200' };
    default:
      return { bg: 'bg-slate-50', text: 'text-slate-700', border: 'border-slate-200' };
  }
}

export const AccountFilesView: React.FC<AccountFilesViewProps> = ({ activeRole }) => {
  const [searchInput, setSearchInput] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | ''>('');
  const [page, setPage] = useState(1);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const filesQuery = useQuery({
    queryKey: ['document-versions', statusFilter, appliedSearch, page],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/document-versions', {
          params: {
            query: {
              status: statusFilter || undefined,
              search: appliedSearch.trim() || undefined,
              page,
              page_size: 25,
            },
          },
        }),
      ),
  });

  const items = filesQuery.data?.items ?? [];
  const total = filesQuery.data?.total ?? 0;
  const pageSize = filesQuery.data?.page_size ?? 25;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setAppliedSearch(searchInput);
    setPage(1);
  };

  const handleClearSearch = () => {
    setSearchInput('');
    setAppliedSearch('');
    setPage(1);
  };

  const handleDownload = async (versionId: string) => {
    if (downloadingId) return;
    setDownloadingId(versionId);
    setDownloadError(null);
    try {
      const download = await apiData(
        api.GET('/api/v1/document-versions/{version_id}/download', {
          params: { path: { version_id: versionId } },
        }),
      );
      const link = document.createElement('a');
      link.href = download.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      setDownloadError(getErrorMessage(err));
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div>
      <AccountNav activeRole={activeRole} />
      <div className="p-4 sm:p-8 max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Document Files</h1>
            <p className="text-sm text-[#596579] mt-1">
              Access and download submissions and document versions available to your role.
            </p>
          </div>
          <button
            type="button"
            disabled={filesQuery.isFetching}
            onClick={() => void filesQuery.refetch()}
            className="self-start sm:self-auto inline-flex items-center gap-1.5 px-3 py-2 border border-[#DDE2E8] bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 rounded-lg transition-colors disabled:opacity-50"
            title="Refresh files"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${filesQuery.isFetching ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Search & Filters */}
        <div className="bg-white border border-[#DDE2E8] rounded-xl p-4 flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
          <form onSubmit={handleSearchSubmit} className="flex-1 flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                aria-label="Search document files"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search filename, assignment, course..."
                className="w-full pl-9 pr-8 py-2 border border-slate-300 rounded-lg text-xs sm:text-sm text-slate-900 placeholder:text-slate-400 focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A] focus:border-[#1F4B7A]"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={handleClearSearch}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                  aria-label="Clear search"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
            <button
              type="submit"
              className="px-3 py-2 bg-[#1F4B7A] hover:bg-[#163657] text-white text-xs sm:text-sm font-semibold rounded-lg transition-colors shrink-0"
            >
              Search
            </button>
          </form>

          <div className="flex items-center gap-2 shrink-0">
            <label htmlFor="status-filter" className="text-xs font-medium text-[#596579] shrink-0">
              Status:
            </label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as DocumentStatus | '');
                setPage(1);
              }}
              className="px-2.5 py-2 border border-slate-300 rounded-lg text-xs sm:text-sm text-slate-900 bg-white focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A]"
            >
              <option value="">All statuses</option>
              {documentStatuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Download Error Alert */}
        {downloadError && (
          <div
            role="alert"
            className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center justify-between"
          >
            <span>Download failed: {downloadError}</span>
            <button
              type="button"
              onClick={() => setDownloadError(null)}
              aria-label="Dismiss download error"
              className="text-rose-700 font-bold ml-2"
            >
              ×
            </button>
          </div>
        )}

        {/* Main Content: Table & Cards */}
        {filesQuery.isLoading ? (
          <div className="bg-white border border-[#DDE2E8] rounded-xl p-12 text-center text-slate-400 flex flex-col items-center gap-3">
            <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
            <span className="text-sm">Loading document files...</span>
          </div>
        ) : filesQuery.isError ? (
          <div className="bg-white border border-[#DDE2E8] rounded-xl p-8 text-center text-rose-600 space-y-3">
            <p className="text-sm font-medium">{getErrorMessage(filesQuery.error)}</p>
            <button
              type="button"
              onClick={() => void filesQuery.refetch()}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-[#1F4B7A] text-white rounded-lg text-xs font-semibold"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="bg-white border border-[#DDE2E8] rounded-xl p-12 text-center text-slate-400">
            <FolderOpen className="w-10 h-10 mx-auto mb-2 text-slate-300 stroke-1" />
            <p className="font-semibold text-slate-700 text-sm">No document versions found</p>
            <p className="text-xs text-slate-400 mt-1">
              {appliedSearch || statusFilter
                ? 'Try adjusting your search query or status filter.'
                : 'No document files have been uploaded in your accessible scope.'}
            </p>
          </div>
        ) : (
          <>
            {/* Desktop Table View */}
            <div className="hidden md:block bg-white border border-[#DDE2E8] rounded-xl overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-[#F5F7FA] border-b border-[#DDE2E8] text-[#596579] font-semibold">
                  <tr>
                    <th className="p-3.5">Filename / Version</th>
                    <th className="p-3.5">Course & Assignment</th>
                    <th className="p-3.5">Status</th>
                    {activeRole !== 'student' && <th className="p-3.5">Student</th>}
                    <th className="p-3.5">Size</th>
                    <th className="p-3.5">Uploaded</th>
                    <th className="p-3.5 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {items.map((item: DocumentVersionItem) => {
                    const statusBadge = getStatusBadge(item.document_status);
                    const isDownloading = downloadingId === item.document_version_id;

                    return (
                      <tr key={item.document_version_id} className="hover:bg-slate-50 transition-colors">
                        <td className="p-3.5">
                          <div className="flex items-center gap-2">
                            <FileText className="w-4 h-4 text-[#1F4B7A] shrink-0" />
                            <span className="font-semibold text-slate-900 truncate max-w-[200px]" title={item.filename}>
                              {item.filename}
                            </span>
                            <span className="px-1.5 py-0.2 bg-slate-100 text-slate-600 rounded text-[10px] font-mono shrink-0">
                              v{item.version_number}
                            </span>
                          </div>
                        </td>
                        <td className="p-3.5">
                          <p className="font-medium text-slate-900 truncate max-w-[200px]" title={item.assignment_title}>
                            {item.assignment_title}
                          </p>
                          <p className="text-[11px] text-[#8893A5] truncate max-w-[200px]">
                            {item.course_code} · {item.course_name}
                          </p>
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${statusBadge.bg} ${statusBadge.text} ${statusBadge.border}`}
                          >
                            {item.document_status}
                          </span>
                        </td>
                        {activeRole !== 'student' && (
                          <td className="p-3.5 text-slate-700 truncate max-w-[140px]">
                            {item.student_display_name || '—'}
                          </td>
                        )}
                        <td className="p-3.5 text-[#596579] whitespace-nowrap">
                          {formatBytes(item.file_size_bytes)}
                        </td>
                        <td className="p-3.5 text-[#8893A5] whitespace-nowrap">
                          {new Date(item.created_at).toLocaleDateString()}
                        </td>
                        <td className="p-3.5 text-right">
                          <button
                            type="button"
                            disabled={isDownloading || downloadingId !== null}
                            onClick={() => void handleDownload(item.document_version_id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 border border-[#DDE2E8] hover:bg-slate-100 text-slate-700 rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
                            title="Download document file"
                          >
                            {isDownloading ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin text-[#1F4B7A]" />
                            ) : (
                              <Download className="w-3.5 h-3.5" />
                            )}
                            <span>Download</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile Card List */}
            <div className="md:hidden space-y-3">
              {items.map((item: DocumentVersionItem) => {
                const statusBadge = getStatusBadge(item.document_status);
                const isDownloading = downloadingId === item.document_version_id;

                return (
                  <div
                    key={item.document_version_id}
                    className="bg-white border border-[#DDE2E8] rounded-xl p-4 space-y-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="w-4 h-4 text-[#1F4B7A] shrink-0" />
                        <span className="font-semibold text-slate-900 text-xs truncate" title={item.filename}>
                          {item.filename}
                        </span>
                        <span className="px-1.5 py-0.2 bg-slate-100 text-slate-600 rounded text-[10px] font-mono shrink-0">
                          v{item.version_number}
                        </span>
                      </div>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border shrink-0 ${statusBadge.bg} ${statusBadge.text} ${statusBadge.border}`}
                      >
                        {item.document_status}
                      </span>
                    </div>

                    <div className="text-xs space-y-0.5 text-[#596579]">
                      <p className="font-medium text-slate-900">{item.assignment_title}</p>
                      <p className="text-[11px] text-[#8893A5]">
                        {item.course_code} · {item.course_name}
                      </p>
                      {activeRole !== 'student' && item.student_display_name && (
                        <p className="text-[11px] text-slate-600">Student: {item.student_display_name}</p>
                      )}
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-[11px] text-[#8893A5]">
                      <span>
                        {formatBytes(item.file_size_bytes)} · {new Date(item.created_at).toLocaleDateString()}
                      </span>
                      <button
                        type="button"
                        disabled={isDownloading || downloadingId !== null}
                        onClick={() => void handleDownload(item.document_version_id)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 border border-[#DDE2E8] bg-[#F5F7FA] text-slate-700 rounded-lg text-xs font-medium disabled:opacity-50"
                      >
                        {isDownloading ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Download className="w-3.5 h-3.5" />
                        )}
                        <span>Download</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Pagination */}
        {!filesQuery.isLoading && !filesQuery.isError && total > 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-[#596579]">
            <span>
              Showing {items.length} of {total} file{total === 1 ? '' : 's'} · Page {page} of{' '}
              {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1 || filesQuery.isFetching}
                onClick={() => setPage((p) => p - 1)}
                className="px-3 py-1.5 border border-[#DDE2E8] bg-white rounded-lg font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={page >= totalPages || filesQuery.isFetching}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 border border-[#DDE2E8] bg-white rounded-lg font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
