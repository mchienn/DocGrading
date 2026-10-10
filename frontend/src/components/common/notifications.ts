import React from 'react';
import type { QueryClient } from '@tanstack/react-query';
import {
  Bell,
  CheckCircle2,
  XCircle,
  MessageSquare,
  AlertTriangle,
} from 'lucide-react';
import { api, apiData } from '../../api/client';
import type { components } from '../../api/schema';
import type { WorkspaceRole } from '../../types/api';

export type NotificationItem = components['schemas']['NotificationResponse'];

export interface NotificationMeta {
  title: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
  badgeBg: string;
}

export function getNotificationMeta(type: string): NotificationMeta {
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

export async function markSingleNotificationRead(
  notificationId: string,
  queryClient: QueryClient,
): Promise<void> {
  await apiData(
    api.PATCH('/api/v1/notifications/{notification_id}/read', {
      params: { path: { notification_id: notificationId } },
    }),
  );
  void queryClient.invalidateQueries({ queryKey: ['notifications'] });
}

export async function markAllNotificationsRead(queryClient: QueryClient): Promise<void> {
  while (true) {
    const res = await apiData(
      api.GET('/api/v1/notifications', {
        params: { query: { unread: true, page: 1, page_size: 100 } },
      }),
    );

    const unreadIds = res.items.filter((item) => !item.read_at).map((item) => item.id);
    if (unreadIds.length === 0) break;

    await apiData(
      api.PATCH('/api/v1/notifications/read', {
        body: { notification_ids: unreadIds },
      }),
    );

    if (res.items.length < 100) break;
  }

  void queryClient.invalidateQueries({ queryKey: ['notifications'] });
}

export async function navigateToNotificationTarget(
  notification: NotificationItem,
  activeRole: WorkspaceRole,
  navigate: (path: string) => void,
  onError: (msg: string) => void,
  queryClient: QueryClient,
): Promise<void> {
  if (!notification.read_at) {
    await markSingleNotificationRead(notification.id, queryClient);
  }

  const { type, payload } = notification;
  if (type === 'REVIEW_REQUEST_CREATED') {
    const requestId = payload?.review_request_id;
    if (requestId && typeof requestId === 'string') {
      void queryClient.invalidateQueries({ queryKey: ['review-requests'] });
      const basePath = activeRole === 'admin' ? '/admin/appeals' : '/teacher/appeals';
      navigate(`${basePath}?requestId=${encodeURIComponent(requestId)}`);
    }
  } else if (type === 'RESULT_PUBLISHED') {
    const submissionId = payload?.submission_id;
    if (submissionId && typeof submissionId === 'string' && activeRole === 'student') {
      navigate(`/student/submissions/${encodeURIComponent(submissionId)}/result`);
    } else if (activeRole !== 'student') {
      onError('Published results are available only in the Student workspace.');
    }
  } else if (type === 'REVIEW_REQUEST_RESOLVED' || type === 'REVIEW_REQUEST_REJECTED') {
    const requestId = payload?.review_request_id;
    if (requestId && typeof requestId === 'string') {
      if (activeRole === 'student') {
        navigate(`/student/appeals/${encodeURIComponent(requestId)}`);
      } else {
        navigate(`/${activeRole}/appeals?requestId=${encodeURIComponent(requestId)}`);
      }
    }
  } else if (type === 'ANALYSIS_JOB_ERROR') {
    const jobId = payload?.analysis_job_id;
    if (jobId && typeof jobId === 'string') {
      navigate(`/jobs/${encodeURIComponent(jobId)}`);
    }
  }
}
