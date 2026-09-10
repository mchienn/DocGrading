import React, { useEffect, useState } from 'react';
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import type { components } from '../api/schema';
import {
  authChannel,
  AUTH_EXPIRED_EVENT,
  ApiError,
  api,
  apiData,
  broadcastAuthChange,
  getErrorMessage,
} from '../api/client';
import { AppHeader } from '../components/common/AppHeader';
import { AppSidebar } from '../components/common/AppSidebar';
import { AuthShell } from '../components/auth/AuthShell';
import { CourseListView } from '../components/teacher/CourseListView';
import { CourseWorkspaceView } from '../components/teacher/CourseWorkspaceView';
import { RubricTemplatesView } from '../components/teacher/RubricTemplatesView';
import { StudentAssignmentsView } from '../components/student/StudentAssignmentsView';
import { StudentUploadView } from '../components/student/StudentUploadView';
import { StudentStatusTimelineView } from '../components/student/StudentStatusTimelineView';
import { LoginPage } from '../pages/LoginPage';
import { authService } from '../services/authService';
import type { UserSession } from '../types/auth';
import { strongestRole, type WorkspaceRole } from '../types/api';

type AssignmentInput = components['schemas']['AssignmentCreate'];

function defaultPath(role: WorkspaceRole): string {
  return role === 'student' ? '/student/assignments' : `/${role}/courses`;
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

  const saveCourse = async (input: { code: string; name: string; term: string }, courseId?: string) => {
    if (courseId) {
      await apiData(api.PUT('/api/v1/courses/{course_id}', {
        params: { path: { course_id: courseId } },
        body: { name: input.name, term: input.term },
      }));
    } else {
      await apiData(api.POST('/api/v1/courses', { body: input }));
    }
    await queryClient.invalidateQueries({ queryKey: ['courses'] });
  };

  const archiveCourse = async (courseId: string) => {
    await apiData(api.POST('/api/v1/courses/{course_id}/archive', {
      params: { path: { course_id: courseId } },
    }));
    await queryClient.invalidateQueries({ queryKey: ['courses'] });
  };

  return (
    <CourseListView
      courses={coursesQuery.data ?? []}
      canCreate={role === 'teacher'}
      loading={coursesQuery.isLoading}
      error={coursesQuery.error ? getErrorMessage(coursesQuery.error) : undefined}
      onSelectCourse={(course) => navigate(`/${role}/courses/${course.id}`)}
      onSave={saveCourse}
      onArchive={archiveCourse}
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
      rubrics={(rubricsQuery.data ?? []).filter((rubric) => rubric.status === 'PUBLISHED')}
      loading={assignmentsQuery.isLoading || rubricsQuery.isLoading}
      error={assignmentsQuery.error || rubricsQuery.error ? getErrorMessage(assignmentsQuery.error ?? rubricsQuery.error) : undefined}
      onBack={() => navigate(`/${role}/courses`)}
      onSaveAssignment={saveAssignment}
      onPublishAssignment={publishAssignment}
      onCloseAssignment={closeAssignment}
    />
  );
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
    window.addEventListener(AUTH_EXPIRED_EVENT, expire);
    authChannel.addEventListener('message', expire);
    return () => {
      window.removeEventListener(AUTH_EXPIRED_EVENT, expire);
      authChannel.removeEventListener('message', expire);
    };
  }, [queryClient]);

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
          broadcastAuthChange();
          setAuthExpired(false);
          navigate('/');
        }} />
      </AuthShell>
    );
  }

  const user = sessionQuery.data;
  const activeRole = strongestRole(user.roles);
  const home = defaultPath(activeRole);
  const title = location.pathname.includes('/rubrics')
    ? 'Rubrics'
    : location.pathname.includes('/upload')
      ? 'Upload'
      : location.pathname.startsWith('/jobs/')
        ? 'Processing status'
        : activeRole === 'student'
          ? 'Assignments'
          : 'Courses';

  const logout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await authService.logout();
      setLogoutError(undefined);
      broadcastAuthChange();
      setAuthExpired(true);
      clearUserData(queryClient);
      navigate('/');
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
        onLogout={logout}
      />
      <div className="flex-1 min-w-0">
        <AppHeader activeRole={activeRole} title={title} />
        <main>
          <Routes>
            <Route path="/" element={<Navigate to={home} replace />} />
            <Route path="/teacher/courses" element={activeRole === 'teacher' ? <CoursesPage role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/courses/:courseId" element={activeRole === 'teacher' ? <CoursePage role="teacher" /> : <Navigate to={home} replace />} />
            <Route path="/teacher/rubrics" element={activeRole === 'teacher' ? <RubricTemplatesView /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses" element={activeRole === 'admin' ? <CoursesPage role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/courses/:courseId" element={activeRole === 'admin' ? <CoursePage role="admin" /> : <Navigate to={home} replace />} />
            <Route path="/admin/rubrics" element={activeRole === 'admin' ? <RubricTemplatesView /> : <Navigate to={home} replace />} />
            <Route path="/student/assignments" element={activeRole === 'student' ? <StudentAssignmentsView /> : <Navigate to={home} replace />} />
            <Route path="/student/assignments/:courseId/:assignmentId/upload" element={activeRole === 'student' ? <StudentUploadView /> : <Navigate to={home} replace />} />
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
