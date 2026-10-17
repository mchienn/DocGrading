import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Bell,
  Check,
  CheckCheck,
  Loader2,
  RefreshCw,
  Inbox,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { WorkspaceRole } from '../../types/api';
import { AccountNav } from './AccountNav';
import {
  getNotificationMeta,
  markAllNotificationsRead,
  markSingleNotificationRead,
  navigateToNotificationTarget,
  type NotificationItem,
} from '../common/notifications';

interface AccountNotificationsViewProps {
  activeRole: WorkspaceRole;
}

export const AccountNotificationsView: React.FC<AccountNotificationsViewProps> = ({
  activeRole,
}) => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [filterUnread, setFilterUnread] = useState<boolean | null>(null);
  const [page, setPage] = useState(1);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isMarkingAll, setIsMarkingAll] = useState(false);
  const [markingReadId, setMarkingReadId] = useState<string | null>(null);
  const [navigatingId, setNavigatingId] = useState<string | null>(null);

  const notificationsQuery = useQuery({
    queryKey: ['notifications', 'full-page', filterUnread, page],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/notifications', {
          params: {
            query: {
              unread: filterUnread ?? undefined,
              page,
              page_size: 20,
            },
          },
        }),
      ),
  });

  const unreadCountQuery = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/notifications', {
          params: { query: { unread: true, page: 1, page_size: 1 } },
        }),
      ),
  });

  const items = notificationsQuery.data?.items ?? [];
  const total = notificationsQuery.data?.total ?? 0;
  const pageSize = notificationsQuery.data?.page_size ?? 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const unreadCount = unreadCountQuery.data?.total ?? 0;

  const handleMarkSingle = async (notificationId: string) => {
    setMarkingReadId(notificationId);
    setActionError(null);
    try {
      await markSingleNotificationRead(notificationId, queryClient);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setMarkingReadId(null);
    }
  };

  const handleMarkAll = async () => {
    if (unreadCount === 0 || isMarkingAll) return;
    setIsMarkingAll(true);
    setActionError(null);
    try {
      await markAllNotificationsRead(queryClient);
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setIsMarkingAll(false);
    }
  };

  const handleClickNotification = async (notification: NotificationItem) => {
    if (navigatingId !== null) return;
    setNavigatingId(notification.id);
    setActionError(null);
    try {
      await navigateToNotificationTarget(
        notification,
        activeRole,
        (path) => navigate(path),
        (err) => setActionError(err),
        queryClient,
      );
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setNavigatingId(null);
    }
  };

  return (
    <div>
      <AccountNav activeRole={activeRole} />
      <div className="p-4 sm:p-8 max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900">Notifications</h1>
            <p className="text-sm text-[#596579] mt-1">
              Review system alerts, grading updates, and review requests.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleMarkAll()}
              disabled={unreadCount === 0 || isMarkingAll}
              className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#DDE2E8] bg-white hover:bg-slate-50 text-xs font-semibold text-[#1F4B7A] rounded-lg transition-colors disabled:opacity-50"
            >
              {isMarkingAll ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <CheckCheck className="w-3.5 h-3.5" />
              )}
              <span>Mark all as read</span>
            </button>

            <button
              type="button"
              disabled={notificationsQuery.isFetching}
              onClick={() => {
                void notificationsQuery.refetch();
                void unreadCountQuery.refetch();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-2 border border-[#DDE2E8] bg-white hover:bg-slate-50 text-xs font-semibold text-slate-700 rounded-lg transition-colors disabled:opacity-50"
              title="Refresh notifications"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${notificationsQuery.isFetching ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-2 border-b border-[#DDE2E8] pb-3">
          <button
            type="button"
            onClick={() => {
              setFilterUnread(null);
              setPage(1);
            }}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              filterUnread === null
                ? 'bg-[#1F4B7A] text-white'
                : 'bg-white border border-[#DDE2E8] text-[#596579] hover:bg-slate-50'
            }`}
          >
            All notifications
          </button>
          <button
            type="button"
            onClick={() => {
              setFilterUnread(true);
              setPage(1);
            }}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              filterUnread === true
                ? 'bg-[#1F4B7A] text-white'
                : 'bg-white border border-[#DDE2E8] text-[#596579] hover:bg-slate-50'
            }`}
          >
            <span>Unread</span>
            {unreadCount > 0 && (
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                  filterUnread === true ? 'bg-white/20 text-white' : 'bg-[#EAF1F8] text-[#1F4B7A]'
                }`}
              >
                {unreadCount}
              </span>
            )}
          </button>
        </div>

        {/* Action Error */}
        {actionError && (
          <div
            role="alert"
            className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center justify-between"
          >
            <span>{actionError}</span>
            <button
              type="button"
              onClick={() => setActionError(null)}
              aria-label="Dismiss error"
              className="text-rose-700 font-bold ml-2"
            >
              ×
            </button>
          </div>
        )}

        {/* List Content */}
        <div className="bg-white border border-[#DDE2E8] rounded-xl overflow-hidden divide-y divide-slate-100">
          {notificationsQuery.isLoading ? (
            <div className="p-12 text-center text-slate-400 flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-[#1F4B7A]" />
              <span className="text-sm">Loading notifications...</span>
            </div>
          ) : notificationsQuery.isError ? (
            <div className="p-8 text-center text-rose-600 space-y-3">
              <p className="text-sm font-medium">{getErrorMessage(notificationsQuery.error)}</p>
              <button
                type="button"
                onClick={() => void notificationsQuery.refetch()}
                className="inline-flex items-center gap-1 px-3 py-1.5 bg-[#1F4B7A] text-white rounded-lg text-xs font-semibold"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Retry
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="p-12 text-center text-slate-400">
              <Inbox className="w-10 h-10 mx-auto mb-2 text-slate-300 stroke-1" />
              <p className="font-semibold text-slate-700 text-sm">
                {filterUnread ? 'No unread notifications' : 'No notifications found'}
              </p>
              <p className="text-xs text-slate-400 mt-1">
                {filterUnread
                  ? 'All notifications have been marked as read.'
                  : 'You have no notifications at this time.'}
              </p>
            </div>
          ) : (
            items.map((item) => {
              const meta = getNotificationMeta(item.type);
              const isUnread = !item.read_at;
              const isNavigating = navigatingId === item.id;
              const isMarking = markingReadId === item.id;
              const IconComponent = meta.Icon;

              return (
                <div
                  key={item.id}
                  className={`p-4 transition-colors flex items-start gap-3 ${
                    isUnread ? 'bg-sky-50/30 hover:bg-sky-50/60' : 'bg-white hover:bg-slate-50'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => void handleClickNotification(item)}
                    disabled={navigatingId !== null || isMarking}
                    className="flex-1 min-w-0 flex items-start gap-3.5 text-left focus:outline-hidden focus-visible:ring-2 focus-visible:ring-[#1F4B7A] rounded-lg p-1 group"
                  >
                    <div
                      className={`p-2.5 rounded-lg border shrink-0 mt-0.5 ${meta.badgeBg} ${meta.iconColor}`}
                    >
                      {isNavigating ? (
                        <Loader2 className="w-4 h-4 animate-spin text-[#1F4B7A]" />
                      ) : (
                        <IconComponent className="w-4 h-4" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-sm truncate ${
                            isUnread ? 'text-slate-900 font-bold' : 'text-slate-700 font-medium'
                          }`}
                        >
                          {meta.title}
                        </span>
                        {isUnread && (
                          <span
                            className="w-2 h-2 rounded-full bg-sky-500 shrink-0"
                            aria-label="Unread"
                          />
                        )}
                      </div>
                      <p className="text-xs text-[#596579] mt-0.5 leading-relaxed">
                        {meta.description}
                      </p>
                      <time
                        dateTime={item.created_at}
                        className="text-[11px] text-[#8893A5] block mt-1.5"
                      >
                        {new Date(item.created_at).toLocaleString()}
                      </time>
                    </div>
                  </button>

                  {isUnread && (
                    <button
                      type="button"
                      aria-label="Mark as read"
                      title="Mark as read"
                      disabled={navigatingId !== null || isMarking}
                      onClick={() => void handleMarkSingle(item.id)}
                      className="shrink-0 p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-40"
                    >
                      {isMarking ? (
                        <Loader2 className="w-4 h-4 animate-spin text-[#1F4B7A]" />
                      ) : (
                        <Check className="w-4 h-4" />
                      )}
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Pagination */}
        {!notificationsQuery.isLoading && !notificationsQuery.isError && total > 0 && (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-[#596579]">
            <span>
              Showing {items.length} of {total} notification{total === 1 ? '' : 's'} · Page {page} of{' '}
              {totalPages}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1 || notificationsQuery.isFetching}
                onClick={() => setPage((p) => p - 1)}
                className="px-3 py-1.5 border border-[#DDE2E8] bg-white rounded-lg font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-40 transition-colors"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={page >= totalPages || notificationsQuery.isFetching}
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
