import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Bell,
  Check,
  CheckCheck,
  CheckCircle2,
  XCircle,
  MessageSquare,
  AlertTriangle,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { api, apiData, getErrorMessage } from '../../api/client';
import type { components } from '../../api/schema';

type NotificationItem = components['schemas']['NotificationResponse'];

function getNotificationMeta(type: string): {
  title: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  badgeBg: string;
} {
  switch (type) {
    case 'REVIEW_REQUEST_CREATED':
      return {
        title: 'Review request submitted',
        description: 'A student requested a review for an evaluation criterion.',
        Icon: MessageSquare,
        iconColor: 'text-amber-600',
        badgeBg: 'bg-amber-50 border-amber-200',
      };
    case 'RESULT_PUBLISHED':
      return {
        title: 'Result published',
        description: 'An evaluation result has been published for your submission.',
        Icon: CheckCircle2,
        iconColor: 'text-emerald-600',
        badgeBg: 'bg-emerald-50 border-emerald-200',
      };
    case 'REVIEW_REQUEST_RESOLVED':
      return {
        title: 'Review request resolved',
        description: 'An instructor resolved your criterion review request.',
        Icon: CheckCircle2,
        iconColor: 'text-emerald-600',
        badgeBg: 'bg-emerald-50 border-emerald-200',
      };
    case 'REVIEW_REQUEST_REJECTED':
      return {
        title: 'Review request rejected',
        description: 'An instructor rejected your criterion review request.',
        Icon: XCircle,
        iconColor: 'text-rose-600',
        badgeBg: 'bg-rose-50 border-rose-200',
      };
    case 'ANALYSIS_JOB_ERROR':
      return {
        title: 'Analysis job failed',
        description: 'An error occurred while processing the document submission.',
        Icon: AlertTriangle,
        iconColor: 'text-rose-600',
        badgeBg: 'bg-rose-50 border-rose-200',
      };
    default:
      return {
        title: 'Notification',
        description: 'New activity on your account.',
        Icon: Bell,
        iconColor: 'text-slate-600',
        badgeBg: 'bg-slate-50 border-slate-200',
      };
  }
}

export const NotificationCenter: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [navigatingId, setNavigatingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isMarkingAll, setIsMarkingAll] = useState(false);

  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    queryFn: () =>
      apiData(
        api.GET('/api/v1/notifications', {
          params: { query: { page: 1, page_size: 50 } },
        }),
      ),
    refetchInterval: 10_000,
  });

  const items = notificationsQuery.data?.items ?? [];
  const unreadItems = items.filter((item) => !item.read_at);
  const unreadCount = unreadItems.length;

  // Handle outside click & Escape key
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    };

    const handleClickOutside = (event: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const markSingleRead = async (notificationId: string) => {
    try {
      await apiData(
        api.PATCH('/api/v1/notifications/{notification_id}/read', {
          params: { path: { notification_id: notificationId } },
        }),
      );
      await queryClient.invalidateQueries({ queryKey: ['notifications'] });
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  };

  const markAllRead = async () => {
    if (unreadItems.length === 0 || isMarkingAll) return;
    setIsMarkingAll(true);
    setActionError(null);
    try {
      await apiData(
        api.PATCH('/api/v1/notifications/read', {
          body: { notification_ids: unreadItems.map((n) => n.id) },
        }),
      );
      await queryClient.invalidateQueries({ queryKey: ['notifications'] });
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setIsMarkingAll(false);
    }
  };

  const handleNotificationClick = async (notification: NotificationItem) => {
    setActionError(null);

    // 1. Mark read if unread
    if (!notification.read_at) {
      void markSingleRead(notification.id);
    }

    // 2. Safe deep linking based strictly on type and typed payload
    try {
      const { type, payload } = notification;
      if (type === 'REVIEW_REQUEST_CREATED') {
        const requestId = payload?.review_request_id;
        if (requestId && typeof requestId === 'string') {
          setIsOpen(false);
          navigate(`/teacher/appeals?requestId=${encodeURIComponent(requestId)}`);
        }
      } else if (type === 'RESULT_PUBLISHED') {
        const submissionId = payload?.submission_id;
        if (submissionId && typeof submissionId === 'string') {
          setIsOpen(false);
          navigate(`/student/submissions/${encodeURIComponent(submissionId)}/result`);
        }
      } else if (type === 'REVIEW_REQUEST_RESOLVED' || type === 'REVIEW_REQUEST_REJECTED') {
        const requestId = payload?.review_request_id;
        if (requestId && typeof requestId === 'string') {
          setNavigatingId(notification.id);
          const requestDetail = await apiData(
            api.GET('/api/v1/review-requests/{review_request_id}', {
              params: { path: { review_request_id: requestId } },
            }),
          );
          setIsOpen(false);
          if (requestDetail.submission_id) {
            navigate(`/student/submissions/${encodeURIComponent(requestDetail.submission_id)}/result`);
          }
        }
      } else if (type === 'ANALYSIS_JOB_ERROR') {
        const jobId = payload?.analysis_job_id;
        if (jobId && typeof jobId === 'string') {
          setIsOpen(false);
          navigate(`/jobs/${encodeURIComponent(jobId)}`);
        }
      }
    } catch (err) {
      setActionError(getErrorMessage(err));
    } finally {
      setNavigatingId(null);
    }
  };

  return (
    <div className="relative inline-block text-left">
      <button
        ref={buttonRef}
        type="button"
        id="notification-bell-btn"
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ''}`}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        aria-controls="notification-panel"
        onClick={() => setIsOpen((prev) => !prev)}
        className="relative p-2 text-[#596579] hover:text-[#172033] hover:bg-[#F3F5F7] rounded-lg transition-colors focus:outline-hidden focus:ring-2 focus:ring-[#1F4B7A]"
      >
        <Bell className="w-4 h-4" />
        {unreadCount > 0 && (
          <span
            data-testid="notification-badge"
            className="absolute -top-0.5 -right-0.5 min-w-[1.125rem] h-[1.125rem] px-1 rounded-full bg-[#B53A3A] text-white text-[10px] font-bold flex items-center justify-center leading-none shadow-xs"
            aria-hidden="true"
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <div
          ref={panelRef}
          id="notification-panel"
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 mt-2 w-80 sm:w-96 bg-white border border-[#DDE2E8] rounded-xl shadow-xl z-50 overflow-hidden text-xs"
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-[#DDE2E8] flex items-center justify-between bg-slate-50">
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-900">Notifications</span>
              {unreadCount > 0 && (
                <span className="px-1.5 py-0.5 rounded-full bg-slate-200 text-slate-700 text-[10px] font-semibold">
                  {unreadCount} new
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                disabled={isMarkingAll}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1F4B7A] hover:text-[#163657] disabled:opacity-50"
              >
                {isMarkingAll ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <CheckCheck className="w-3.5 h-3.5" />
                )}
                <span>Mark all as read</span>
              </button>
)}
          </div>

          {/* Error Message */}
          {actionError && (
            <div
              role="alert"
              className="p-2.5 mx-3 mt-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-[11px]"
            >
              {actionError}
            </div>
          )}

          {/* Content Body */}
          <div className="max-h-96 overflow-y-auto divide-y divide-slate-100">
            {notificationsQuery.isLoading ? (
              <div className="p-8 text-center text-slate-400 flex flex-col items-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>Loading notifications...</span>
              </div>
            ) : notificationsQuery.isError ? (
              <div className="p-6 text-center text-rose-600 space-y-2">
                <p>{getErrorMessage(notificationsQuery.error)}</p>
                <button
                  type="button"
                  onClick={() => void notificationsQuery.refetch()}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1F4B7A] hover:underline"
                >
                  <RefreshCw className="w-3 h-3" /> Retry
                </button>
              </div>
            ) : items.length === 0 ? (
              <div className="p-8 text-center text-slate-400">
                <Bell className="w-8 h-8 mx-auto mb-2 text-slate-300 stroke-1" />
                <p className="font-medium text-slate-600">No notifications</p>
                <p className="text-[11px] text-slate-400 mt-0.5">You're all caught up!</p>
              </div>
            ) : (
              items.map((item) => {
                const meta = getNotificationMeta(item.type);
                const isUnread = !item.read_at;
                const isNavigating = navigatingId === item.id;
                const IconComponent = meta.Icon;

                return (
                  <div
                    key={item.id}
                    data-testid="notification-item"
                    className={`relative p-3 transition-colors flex items-start gap-3 cursor-pointer ${
                      isUnread ? 'bg-sky-50/40 hover:bg-sky-50/70' : 'bg-white hover:bg-slate-50'
                    }`}
                    onClick={() => void handleNotificationClick(item)}
                  >
                    <div
                      className={`p-2 rounded-lg border shrink-0 mt-0.5 ${meta.badgeBg} ${meta.iconColor}`}
                    >
                      {isNavigating ? (
                        <Loader2 className="w-4 h-4 animate-spin text-[#1F4B7A]" />
                      ) : (
                        <IconComponent className="w-4 h-4" />
                      )}
                    </div>

                    <div className="flex-1 min-w-0 pr-6">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`font-semibold truncate ${
                            isUnread ? 'text-slate-900 font-bold' : 'text-slate-700'
                          }`}
                        >
                          {meta.title}
                        </span>
                        {isUnread && (
                          <span
                            className="w-1.5 h-1.5 rounded-full bg-sky-500 shrink-0"
                            aria-label="Unread"
                          />
                        )}
                      </div>
                      <p className="text-slate-500 text-[11px] mt-0.5 leading-relaxed">
                        {meta.description}
                      </p>
                      <time
                        dateTime={item.created_at}
                        className="text-[10px] text-slate-400 block mt-1"
                      >
                        {new Date(item.created_at).toLocaleString()}
                      </time>
                    </div>

                    {isUnread && (
                      <button
                        type="button"
                        aria-label="Mark as read"
                        title="Mark as read"
                        onClick={(e) => {
                          e.stopPropagation();
                          void markSingleRead(item.id);
                        }}
                        className="absolute right-2.5 top-3 p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-md transition-colors"
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
};
