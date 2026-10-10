import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import type { components } from '../api/schema';
import {
  authChannel,
  AUTH_EXPIRED_EVENT,
  ApiError,
  api,
  apiData,
  apiVoid,
  broadcastAuthChange,
  getErrorMessage,
  type AuthChangeKind,
} from '../api/client';
import { AppHeader } from '../components/common/AppHeader';
import { AdminDashboardView } from '../components/admin/AdminDashboardView';
import { UserManagementView } from '../components/admin/UserManagementView';
import { JobMonitoringView } from '../components/admin/JobMonitoringView';
import { AuditLogView } from '../components/admin/AuditLogView';
import { LLMProviderSettingsView } from '../components/admin/LLMProviderSettingsView';
import { AppSidebar } from '../components/common/AppSidebar';
import { AuthShell } from '../components/auth/AuthShell';
import { CourseListView } from '../components/teacher/CourseListView';
import { CourseWorkspaceView } from '../components/teacher/CourseWorkspaceView';
import { DocumentGradingResultView } from '../components/teacher/DocumentGradingResultView';
import { CourseRosterView } from '../components/teacher/CourseRosterView';
import { RubricTemplatesView } from '../components/teacher/RubricTemplatesView';
import { SubmissionQueueView } from '../components/teacher/SubmissionQueueView';
import { ReviewWorkspaceView } from '../components/teacher/ReviewWorkspaceView';
import { AppealsInboxView } from '../components/teacher/AppealsInboxView';
import { StudentPublishedResultView } from '../components/student/StudentPublishedResultView';
import { StudentAppealDetailView } from '../components/student/StudentAppealDetailView';
import { StudentAssignmentsView } from '../components/student/StudentAssignmentsView';
import { StudentJoinCourseView } from '../components/student/StudentJoinCourseView';
import { StudentUploadView } from '../components/student/StudentUploadView';
import { StudentStatusTimelineView } from '../components/student/StudentStatusTimelineView';
import { AccountProfileView } from '../components/account/AccountProfileView';
import { AccountNotificationsView } from '../components/account/AccountNotificationsView';
import { AccountFilesView } from '../components/account/AccountFilesView';
import { AccountSettingsView } from '../components/account/AccountSettingsView';
import { LoginPage } from '../pages/LoginPage';
import { authService } from '../services/authService';
import type { UserSession } from '../types/auth';
import { strongestRole, type ApiCourse, type ApiUser, type WorkspaceRole } from '../types/api';

type AssignmentInput = components['schemas']['AssignmentCreate'];
type AnnouncementInput = components['schemas']['AnnouncementCreate'];

function defaultPath(role: WorkspaceRole): string {
  if (role === 'admin') return '/admin/dashboard';
  return role === 'student' ? '/student/assignments' : '/teacher/courses';
}

function clearUserData(queryClient: QueryClient): void {
  queryClient.removeQueries({
    predicate: (query) => query.queryKey[0] !== 'session',
  });
}

const CoursesPage: React.FC<{ role: 'teacher' | 'admin' }> = ({ role }) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const coursesQuery = useQuery({
    queryKey: ['courses'],
    queryFn: () => apiData(api.GET('/api/v1/courses')),
  });
  const teachersQuery = useQuery({
    queryKey: ['admin-users', 'course-owners'],
    queryFn: async () => {
      const loadPage = (page: number) => apiData(api.GET('/api/v1/users', {
        params: {
          query: {
            role: 'TEACHER',
            status: 'ACTIVE',
            page,
            page_size: 100,
          },
        },
      }));
      const firstPage = await loadPage(1);
      const owners: ApiUser[] = [...firstPage.items];
      for (let page = 2; page <= Math.ceil(firstPage.total / 100); page += 1) {
        owners.push(...(await loadPage(page)).items);
      }
      return owners;
    },
    enabled: role === 'admin',
  });

  const saveCourse = async (
    input: { code: string; name: string; term: string; ownerTeacherId?: string },
    course?: ApiCourse,
  ) => {
    if (course) {
      await apiData(api.PUT('/api/v1/courses/{course_id}', {
        params: {
          path: { course_id: course.id },
          header: { 'If-Match': `"rev-${course.revision}"` },
        },
        body: { name: input.name, term: input.term },
      }));
    } else {
      await apiData(api.POST('/api/v1/courses', {
        body: {
          code: input.code,
          name: input.name,
          term: input.term,
          owner_teacher_id: input.ownerTeacherId,
        },
      }));
    }
    await queryClient.invalidateQueries({ queryKey: ['courses'] });
  };

  const archiveCourse = async (course: ApiCourse) => {
    await apiData(api.POST('/api/v1/courses/{course_id}/archive', {
      params: {
        path: { course_id: course.id },
        header: { 'If-Match': `"rev-${course.revision}"` },
      },
    }));
    await queryClient.invalidateQueries({ queryKey: ['courses'] });
  };

  const deleteCourse = async (course: ApiCourse) => {
    await apiVoid(api.DELETE('/api/v1/courses/{course_id}', {
      params: {
        path: { course_id: course.id },
        header: { 'If-Match': `"rev-${course.revision}"` },
      },
    }));
    await queryClient.invalidateQueries({ queryKey: ['courses'] });
  };

  return (
    <CourseListView
      role={role}
      ownerOptions={role === 'admin' ? teachersQuery.data ?? [] : undefined}
      courses={coursesQuery.data ?? []}
      canCreate={role === 'teacher' || role === 'admin'}
      canDelete={role === 'admin'}
      loading={coursesQuery.isLoading}
      error={
        coursesQuery.error || teachersQuery.error
          ? getErrorMessage(coursesQuery.error ?? teachersQuery.error)
          : undefined
      }
      onSelectCourse={(course) => navigate(`/${role}/courses/${course.id}`)}
      onSave={saveCourse}
      onArchive={archiveCourse}
      onDelete={deleteCourse}
    />
  );
};

const CoursePage: React.FC<{ role: 'teacher' | 'admin' }> = ({ role }) => {
  const { courseId = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const courseQuery = useQuery({
    queryKey: ['course', courseId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}', {
      params: { path: { course_id: courseId } },
    })),
    enabled: Boolean(courseId),
  });
  const assignmentsQuery = useQuery({
    queryKey: ['assignments', courseId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/assignments', {
      params: { path: { course_id: courseId } },
    })),
    enabled: Boolean(courseId),
  });
  const announcementsQuery = useQuery({
    queryKey: ['announcements', courseId],
    queryFn: () => apiData(api.GET('/api/v1/courses/{course_id}/announcements', {
      params: { path: { course_id: courseId } },
    })),
    enabled: Boolean(courseId),
  });
  const rubricsQuery = useQuery({
    queryKey: ['rubrics'],
    queryFn: () => apiData(api.GET('/api/v1/rubrics')),
  });

  const refreshAssignments = async () => {
    await queryClient.invalidateQueries({ queryKey: ['assignments', courseId] });
  };

  const saveAssignment = async (input: AssignmentInput, assignmentId?: string) => {
    if (assignmentId) {
      await apiData(api.PUT('/api/v1/courses/{course_id}/assignments/{assignment_id}', {
        params: { path: { course_id: courseId, assignment_id: assignmentId } },
        body: input,
      }));
    } else {
      await apiData(api.POST('/api/v1/courses/{course_id}/assignments', {
        params: { path: { course_id: courseId } },
        body: input,
      }));
    }
    await refreshAssignments();
  };

  const deleteAssignment = async (assignmentId: string) => {
    await apiVoid(api.DELETE('/api/v1/courses/{course_id}/assignments/{assignment_id}', {
      params: { path: { course_id: courseId, assignment_id: assignmentId } },
    }));
    await refreshAssignments();
  };

  const saveAnnouncement = async (input: AnnouncementInput, announcementId?: string) => {
    if (announcementId) {
      await apiData(api.PUT('/api/v1/courses/{course_id}/announcements/{announcement_id}', {
        params: { path: { course_id: courseId, announcement_id: announcementId } },
        body: input,
      }));
    } else {
      await apiData(api.POST('/api/v1/courses/{course_id}/announcements', {
        params: { path: { course_id: courseId } },
        body: input,
      }));
    }
    await queryClient.invalidateQueries({ queryKey: ['announcements', courseId] });
  };

  const deleteAnnouncement = async (announcementId: string) => {
    await apiVoid(api.DELETE('/api/v1/courses/{course_id}/announcements/{announcement_id}', {
      params: { path: { course_id: courseId, announcement_id: announcementId } },
    }));
    await queryClient.invalidateQueries({ queryKey: ['announcements', courseId] });
  };

  const publishAssignment = async (assignmentId: string) => {
    await apiData(api.POST('/api/v1/courses/{course_id}/assignments/{assignment_id}/publish', {
      params: { path: { course_id: courseId, assignment_id: assignmentId } },
    }));
    await refreshAssignments();
  };

  const closeAssignment = async (assignmentId: string) => {
    await apiData(api.POST('/api/v1/courses/{course_id}/assignments/{assignment_id}/close', {
      params: { path: { course_id: courseId, assignment_id: assignmentId } },
    }));
    await refreshAssignments();
  };

  if (courseQuery.isLoading) return <p className="p-8 text-sm text-slate-500">Loading course...</p>;
  if (!courseQuery.data) {
    return <p role="alert" className="p-8 text-sm text-rose-700">{getErrorMessage(courseQuery.error)}</p>;
  }

  return (
    <CourseWorkspaceView
      course={courseQuery.data}
      assignments={assignmentsQuery.data ?? []}
      rubrics={rubricsQuery.data ?? []}
      announcements={announcementsQuery.data ?? []}
      loading={assignmentsQuery.isLoading || rubricsQuery.isLoading || announcementsQuery.isLoading}
      error={assignmentsQuery.error || rubricsQuery.error || announcementsQuery.error
        ? getErrorMessage(assignmentsQuery.error ?? rubricsQuery.error ?? announcementsQuery.error)
        : undefined}
      onBack={() => navigate(`/${role}/courses`)}
      onOpenSubmissionQueue={() => navigate(`/${role}/courses/${courseId}/submissions`)}
      onOpenRoster={() => navigate(`/${role}/courses/${courseId}/roster`)}
      onSaveAssignment={saveAssignment}
      onOpenSubmission={(submissionId, documentStatus) => navigate(
        `/${role}/courses/${courseId}/submissions/${submissionId}`,
        { state: { documentStatus } },
      )}
      onOpenVersionResult={(versionId) => navigate(
        `/${role}/courses/${courseId}/document-versions/${versionId}/result`,
      )}
      onPublishAssignment={publishAssignment}
      onDeleteAssignment={deleteAssignment}
      onCloseAssignment={closeAssignment}
      onSaveAnnouncement={saveAnnouncement}
      onDeleteAnnouncement={deleteAnnouncement}
    />
  );
};

const LogoutRoute: React.FC<{ onLogout: () => Promise<void> }> = ({ onLogout }) => {
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void onLogout();
  }, [onLogout]);
  return <p className="p-8 text-sm text-slate-500">Logging out...</p>;
};

export const App: React.FC = () => {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [authExpired, setAuthExpired] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string>();
  const sessionQuery = useQuery<UserSession>({
    queryKey: ['session'],
    queryFn: authService.loadSession,
    retry: false,
    enabled: !authExpired,
  });

  useEffect(() => {
    const expire = () => {
      clearUserData(queryClient);
      setAuthExpired(true);
    };
    const onAuthChange = (event: MessageEvent<AuthChangeKind>) => {
      clearUserData(queryClient);
      if (event.data === 'signed-in') {
        setAuthExpired(false);
        void sessionQuery.refetch();
        return;
      }
      setAuthExpired(true);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, expire);
    authChannel.addEventListener('message', onAuthChange);
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
      authChannel.removeEventListener('message', onAuthChange);
    };
  }, [queryClient, sessionQuery]);

  if (sessionQuery.isLoading && !authExpired) {
    return <div className="min-h-screen grid place-items-center text-sm text-slate-500">Loading session...</div>;
  }

  const unauthorized = authExpired || (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401);
  if (!sessionQuery.data && !unauthorized) {
    return (
      <div className="min-h-screen grid place-items-center p-6 text-center">
        <div>
          <p role="alert" className="text-sm text-rose-700">{getErrorMessage(sessionQuery.error)}</p>
          <button type="button" onClick={() => sessionQuery.refetch()} className="mt-3 px-4 py-2 bg-slate-900 text-white rounded-lg text-sm">Retry</button>
        </div>
      </div>
    );
  }

  if (!sessionQuery.data || unauthorized) {
    return (
      <AuthShell>
        <LoginPage onLoginSuccess={(user) => {
          clearUserData(queryClient);
          queryClient.setQueryData(['session'], user);
          broadcastAuthChange('signed-in');
          setAuthExpired(false);
          const returnUrl = location.pathname === '/student/join'
            ? `${location.pathname}${location.search}`
            : '/';
          navigate(returnUrl);
        }} />
      </AuthShell>
    );
  }

  const user = sessionQuery.data;
  const activeRole = strongestRole(user.roles);
  const home = defaultPath(activeRole);
  const adminTitles: Record<string, string> = {
    '/admin/dashboard': 'Admin dashboard',
    '/admin/users': 'Users',
    '/admin/jobs': 'Analysis jobs',
    '/admin/audit': 'Audit trail',
    '/admin/appeals': 'Appeals',
    '/admin/ai-providers': 'AI providers',
  };
  const title = location.pathname.endsWith('/profile')
    ? 'Profile'
    : location.pathname.endsWith('/notifications')
    ? 'Notifications'
    : location.pathname.endsWith('/files')
    ? 'Files'
    : location.pathname.endsWith('/settings')
    ? 'Settings'
    : location.pathname.endsWith('/roster')
    ? 'Course roster'
    : (
    adminTitles[location.pathname] ?? (
      location.pathname.startsWith('/teacher/appeals') || location.pathname.startsWith('/admin/appeals')
        ? 'Appeals'
        : location.pathname.startsWith('/student/appeals')
          ? 'Appeal Detail'
          : location.pathname === '/student/join'
            ? 'Join course'
            : location.pathname.includes('/rubrics')
              ? 'Rubrics'
              : location.pathname.includes('/upload')
                ? 'Upload'
                : location.pathname.startsWith('/jobs/')
                  ? 'Processing status'
                  : activeRole === 'student'
                    ? 'Assignments'
                    : 'Courses'
    )
  );

  const logout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await authService.logout();
      setLogoutError(undefined);
      broadcastAuthChange('signed-out');
      setAuthExpired(true);
      clearUserData(queryClient);
      navigate('/', { replace: true });
    } catch (error) {
      setLogoutError(`Logout failed; session may still be active. ${getErrorMessage(error)}`);
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F5F7FA] text-[#172033] flex">
      <AppSidebar
        activeRole={activeRole}
        displayName={user.display_name}
        currentPath={location.pathname}
        onNavigate={navigate}
        onLogout={() => navigate('/logout', { replace: true })}
      />
      <div className="flex-1 min-w-0">
        <AppHeader activeRole={activeRole} title={title} />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to={home} replace />} />
            <Route path="/logout" element={<LogoutRoute onLogout={logout} />} />
            <Route path="/teacher/courses" element={activeRole === 'teacher' ? <CoursesPage role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId" element={activeRole === 'teacher' ? <CoursePage role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId/roster" element={activeRole === 'teacher' ? <CourseRosterView role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/rubrics" element={activeRole === 'teacher' ? <RubricTemplatesView /> : <Navigate to={home} replace />} />
            <Route path="/teacher/appeals" element={activeRole === 'teacher' ? <AppealsInboxView /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId/submissions" element={activeRole === 'teacher' ? <SubmissionQueueView role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId/submissions/:submissionId" element={activeRole === 'teacher' ? <ReviewWorkspaceView role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId/document-versions/:versionId/result" element={activeRole === 'teacher' ? <DocumentGradingResultView /> : <Navigate to={home} replace />} />
            <Route path="/teacher/profile" element={activeRole === 'teacher' ? <AccountProfileView activeRole="teacher" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/teacher/notifications" element={activeRole === 'teacher' ? <AccountNotificationsView activeRole="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/files" element={activeRole === 'teacher' ? <AccountFilesView activeRole="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/settings" element={activeRole === 'teacher' ? <AccountSettingsView activeRole="teacher" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses" element={activeRole === 'admin' ? <CoursesPage role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/dashboard" element={activeRole === 'admin' ? <AdminDashboardView /> : <Navigate to={home} replace />} />
            <Route path="/admin/users" element={activeRole === 'admin' ? <UserManagementView currentUserId={user.id} /> : <Navigate to={home} replace />} />
            <Route path="/admin/jobs" element={activeRole === 'admin' ? <JobMonitoringView /> : <Navigate to={home} replace />} />
            <Route path="/admin/audit" element={activeRole === 'admin' ? <AuditLogView /> : <Navigate to={home} replace />} />
            <Route path="/admin/appeals" element={activeRole === 'admin' ? <AppealsInboxView /> : <Navigate to={home} replace />} />
            <Route path="/admin/ai-providers" element={activeRole === 'admin' ? <LLMProviderSettingsView /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId" element={activeRole === 'admin' ? <CoursePage role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId/roster" element={activeRole === 'admin' ? <CourseRosterView role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/rubrics" element={activeRole === 'admin' ? <RubricTemplatesView /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId/submissions" element={activeRole === 'admin' ? <SubmissionQueueView role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId/submissions/:submissionId" element={activeRole === 'admin' ? <ReviewWorkspaceView role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId/document-versions/:versionId/result" element={activeRole === 'admin' ? <DocumentGradingResultView /> : <Navigate to={home} replace />} />
            <Route path="/admin/profile" element={activeRole === 'admin' ? <AccountProfileView activeRole="admin" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/admin/notifications" element={activeRole === 'admin' ? <AccountNotificationsView activeRole="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/files" element={activeRole === 'admin' ? <AccountFilesView activeRole="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/settings" element={activeRole === 'admin' ? <AccountSettingsView activeRole="admin" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/student/assignments" element={activeRole === 'student' ? <StudentAssignmentsView /> : <Navigate to={home} replace />} />
            <Route path="/student/join" element={activeRole === 'student' ? <StudentJoinCourseView /> : <Navigate to={home} replace />} />
            <Route path="/student/assignments/:courseId/:assignmentId/upload" element={activeRole === 'student' ? <StudentUploadView /> : <Navigate to={home} replace />} />
            <Route path="/student/submissions/:submissionId/result" element={activeRole === 'student' ? <StudentPublishedResultView /> : <Navigate to={home} replace />} />
            <Route path="/student/appeals/:requestId" element={activeRole === 'student' ? <StudentAppealDetailView /> : <Navigate to={home} replace />} />
            <Route path="/student/profile" element={activeRole === 'student' ? <AccountProfileView activeRole="student" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/student/notifications" element={activeRole === 'student' ? <AccountNotificationsView activeRole="student" /> : <Navigate to={home} replace />} />
            <Route path="/student/files" element={activeRole === 'student' ? <AccountFilesView activeRole="student" /> : <Navigate to={home} replace />} />
            <Route path="/student/settings" element={activeRole === 'student' ? <AccountSettingsView activeRole="student" user={user} /> : <Navigate to={home} replace />} />
            <Route path="/jobs/:jobId" element={<StudentStatusTimelineView activeRole={activeRole} />} />
            <Route path="*" element={<Navigate to={home} replace />} />
          </Routes>
        </main>
      </div>
      {logoutError && (
        <div className="fixed inset-0 z-50 bg-[#F5F7FA] grid place-items-center p-6">
          <div role="alert" className="max-w-md bg-white border border-rose-200 rounded-xl p-6 text-center shadow-xl">
            <h2 className="font-bold text-slate-900">Logout not confirmed</h2>
            <p className="text-sm text-rose-700 mt-2">{logoutError}</p>
            <p className="text-xs text-slate-500 mt-2">Retry logout. Close browser if connection cannot be restored.</p>
            <button type="button" disabled={loggingOut} onClick={logout} className="mt-4 px-4 py-2 bg-slate-900 text-white rounded-lg text-sm font-semibold disabled:opacity-50">
              {loggingOut ? 'Retrying...' : 'Retry logout'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
