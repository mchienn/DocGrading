import React, { useState } from 'react';
import { AppHeader } from '../components/common/AppHeader';
import { AppSidebar } from '../components/common/AppSidebar';
import { CourseListView } from '../components/teacher/CourseListView';
import { CourseWorkspaceView } from '../components/teacher/CourseWorkspaceView';
import { AssignmentWizardModal } from '../components/teacher/AssignmentWizardModal';
import { SubmissionQueueView } from '../components/teacher/SubmissionQueueView';
import { ReviewWorkspaceView } from '../components/teacher/ReviewWorkspaceView';
import { AppealsInboxView } from '../components/teacher/AppealsInboxView';
import { StudentAssignmentsView } from '../components/student/StudentAssignmentsView';
import { StudentUploadView } from '../components/student/StudentUploadView';
import { StudentStatusTimelineView } from '../components/student/StudentStatusTimelineView';
import { StudentPublishedResultView } from '../components/student/StudentPublishedResultView';
import { VersionCompareView } from '../components/student/VersionCompareView';
import { AppealModal } from '../components/student/AppealModal';
import { AdminDashboardView } from '../components/admin/AdminDashboardView';
import { UserManagementView } from '../components/admin/UserManagementView';
import { JobMonitoringView } from '../components/admin/JobMonitoringView';
import { AuditLogView } from '../components/admin/AuditLogView';
import { RubricTemplatesView } from '../components/admin/RubricTemplatesView';

// Auth Suite
import { AuthShell } from '../components/auth/AuthShell';
import { ToastProvider } from '../components/auth/Toast';
import { LoginPage } from '../pages/LoginPage';
import { RegisterPage } from '../pages/RegisterPage';
import { ForgotPasswordPage } from '../pages/ForgotPasswordPage';
import { VerifyEmailPage } from '../pages/VerifyEmailPage';
import { ResetPasswordPage } from '../pages/ResetPasswordPage';
import { WorkspaceSuccessPage } from '../pages/WorkspaceSuccessPage';
import { UserSession } from '../types/auth';
import { authService } from '../services/authService';

// Types & Data
import {
  UserRole,
  AppUser,
  Course,
  Assignment,
  Submission,
  CriterionResult,
  EvaluationJob,
  AuditLogItem,
  ReviewAppeal,
} from '../types/docgrading';
import {
  CURRENT_USERS,
  INITIAL_COURSES,
  INITIAL_ASSIGNMENTS,
  INITIAL_SUBMISSIONS,
  INITIAL_JOBS,
  INITIAL_AUDIT_LOGS,
  INITIAL_APPEALS,
} from '../data/mockData';

export default function App() {
  // Global State
  const [activeRole, setActiveRole] = useState<UserRole>('teacher');
  const [currentView, setCurrentView] = useState<string>('teacher_courses');
  const [isAuthMode, setIsAuthMode] = useState<boolean>(false);
  const [authScreen, setAuthScreen] = useState<string>('login');
  const [authenticatedUser, setAuthenticatedUser] = useState<UserSession | null>(() =>
    authService.getCurrentSession()
  );

  // Domain Entities State
  const [courses, setCourses] = useState<Course[]>(INITIAL_COURSES);
  const [assignments, setAssignments] = useState<Assignment[]>(INITIAL_ASSIGNMENTS);
  const [submissions, setSubmissions] = useState<Submission[]>(INITIAL_SUBMISSIONS);
  const [jobs, setJobs] = useState<EvaluationJob[]>(INITIAL_JOBS);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>(INITIAL_AUDIT_LOGS);
  const [appeals, setAppeals] = useState<ReviewAppeal[]>(INITIAL_APPEALS);

  // Users State (for Admin)
  const [usersList, setUsersList] = useState<AppUser[]>([
    CURRENT_USERS.teacher,
    CURRENT_USERS.student,
    CURRENT_USERS.admin,
    {
      id: 'USR-TEACHER-02',
      fullName: 'ThS. Nguyễn Bích Ngọc',
      email: 'ngoc.nb@hust.edu.vn',
      role: 'teacher',
      department: 'Bộ môn Kỹ thuật Phần mềm',
      status: 'active',
      avatarInitials: 'BN',
    },
    {
      id: 'USR-STUDENT-02',
      fullName: 'Trần Thị Thảo',
      email: 'thao.tt218902@sis.hust.edu.vn',
      role: 'student',
      department: 'Kỹ thuật Phần mềm K66',
      status: 'active',
      avatarInitials: 'TT',
    },
  ]);

  // Selected Entities
  const [selectedCourse, setSelectedCourse] = useState<Course>(courses[0]);
  const [selectedAssignment, setSelectedAssignment] = useState<Assignment>(assignments[0]);
  const [selectedSubmission, setSelectedSubmission] = useState<Submission>(submissions[0]);

  // Modals
  const [showAssignmentWizard, setShowAssignmentWizard] = useState(false);
  const [editingAssignment, setEditingAssignment] = useState<Assignment | null>(null);
  const [showAppealModal, setShowAppealModal] = useState(false);

  // Current active user object
  const currentUser = CURRENT_USERS[activeRole] || CURRENT_USERS.teacher;

  // Sync role changes with default view
  const handleRoleChange = (newRole: UserRole) => {
    setActiveRole(newRole);
    setIsAuthMode(false);
    if (newRole === 'teacher') {
      setCurrentView('teacher_courses');
    } else if (newRole === 'student') {
      setCurrentView('student_assignments');
    } else {
      setCurrentView('admin_dashboard');
    }
  };

  // Toast / notification feedback
  const addAuditLog = (action: AuditLogItem['action'], details: string, targetType: string, targetId: string) => {
    const newLog: AuditLogItem = {
      id: `LOG-${Date.now()}`,
      userId: currentUser.id,
      userName: currentUser.fullName,
      action,
      targetType,
      targetId,
      timestamp: new Date().toLocaleString('vi-VN'),
      details,
    };
    setAuditLogs((prev) => [newLog, ...prev]);
  };

  // Teacher Handlers
  const handleCreateCourse = (newCourse: Partial<Course>) => {
    const courseObj: Course = {
      id: `CRS-${Date.now().toString().slice(-3)}`,
      code: newCourse.code || 'SE302',
      name: newCourse.name || 'Môn học mới',
      semester: newCourse.semester || 'Học kỳ 1 - 2026/2027',
      studentCount: 45,
      assignmentCount: 0,
      activeAssignments: 0,
      pendingReviews: 0,
    };
    setCourses((prev) => [...prev, courseObj]);
    setSelectedCourse(courseObj);
    setCurrentView('teacher_workspace');
  };

  const handleSaveAssignment = (assignmentData: Partial<Assignment>) => {
    if (editingAssignment) {
      setAssignments((prev) =>
        prev.map((a) => (a.id === editingAssignment.id ? ({ ...a, ...assignmentData } as Assignment) : a))
      );
      addAuditLog('create_assignment', `Cập nhật đợt nộp: ${assignmentData.title}`, 'Assignment', editingAssignment.id);
    } else {
      const newAsm = assignmentData as Assignment;
      setAssignments((prev) => [newAsm, ...prev]);
      // Update course assignment count
      setCourses((prev) =>
        prev.map((c) =>
          c.id === newAsm.courseId
            ? { ...c, assignmentCount: c.assignmentCount + 1, activeAssignments: c.activeAssignments + 1 }
            : c
        )
      );
      addAuditLog('create_assignment', `Tạo mới đợt nộp bài: ${newAsm.title}`, 'Assignment', newAsm.id);
    }
    setEditingAssignment(null);
    setShowAssignmentWizard(false);
  };

  const handleApproveSubmission = (
    submissionId: string,
    updatedResults: CriterionResult[],
    finalScore: number
  ) => {
    setSubmissions((prev) =>
      prev.map((s) =>
        s.id === submissionId
          ? {
              ...s,
              status: 'approved',
              criteriaResults: updatedResults,
              finalScore,
              reviewerId: currentUser.id,
              reviewerName: currentUser.fullName,
              reviewedAt: new Date().toLocaleString('vi-VN'),
            }
          : s
      )
    );
    addAuditLog(
      'override_score',
      `Giảng viên duyệt điểm bài nộp ${submissionId}: ${finalScore.toFixed(1)}/100`,
      'Submission',
      submissionId
    );
    // Switch to queue
    setCurrentView('teacher_queue');
  };

  const handlePublishSubmission = (submissionId: string) => {
    setSubmissions((prev) =>
      prev.map((s) =>
        s.id === submissionId
          ? {
              ...s,
              status: 'published',
              publishedAt: new Date().toLocaleString('vi-VN'),
            }
          : s
      )
    );
    addAuditLog(
      'publish_result',
      `Công bố kết quả chính thức bài nộp ${submissionId} cho sinh viên.`,
      'Submission',
      submissionId
    );
    setCurrentView('teacher_queue');
  };

  const handleBatchPublish = () => {
    setSubmissions((prev) =>
      prev.map((s) =>
        s.status === 'approved'
          ? {
              ...s,
              status: 'published',
              publishedAt: new Date().toLocaleString('vi-VN'),
            }
          : s
      )
    );
    addAuditLog(
      'publish_result',
      `Công bố kết quả hàng loạt cho các bài nộp đã được duyệt.`,
      'Submission',
      'BATCH'
    );
  };

  const handleRespondAppeal = (
    appealId: string,
    response: string,
    newStatus: 'resolved' | 'rejected'
  ) => {
    setAppeals((prev) =>
      prev.map((a) =>
        a.id === appealId ? { ...a, status: newStatus, teacherResponse: response } : a
      )
    );
    addAuditLog(
      'override_score',
      `Xử lý phúc khảo ${appealId} (${newStatus}): "${response}"`,
      'ReviewAppeal',
      appealId
    );
  };

  // Student Handlers
  const handleStudentUploadSuccess = (newSub: Submission) => {
    setSubmissions((prev) => [newSub, ...prev]);
    setSelectedSubmission(newSub);
    // Add job
    const newJob: EvaluationJob = {
      id: `JOB-${Date.now().toString().slice(-4)}`,
      correlationId: `corr-${Date.now().toString().slice(-6)}`,
      submissionId: newSub.id,
      studentName: newSub.studentName,
      assignmentTitle: newSub.assignmentTitle,
      status: 'running',
      progress: 60,
      evaluator: 'Hybrid: Rule-Engine + LLM-Evaluator v2.4',
      duration: 'Đang xử lý',
      createdAt: new Date().toLocaleTimeString('vi-VN'),
    };
    setJobs((prev) => [newJob, ...prev]);
    setCurrentView('student_status');
  };

  const handleSubmitAppeal = (appealData: Partial<ReviewAppeal>) => {
    const fullAppeal = appealData as ReviewAppeal;
    setAppeals((prev) => [fullAppeal, ...prev]);
  };

  // Admin Handlers
  const handleUpdateUserRole = (userId: string, newRole: UserRole) => {
    setUsersList((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
    );
    addAuditLog(
      'role_change',
      `Thay đổi vai trò người dùng ${userId} thành ${newRole}`,
      'User',
      userId
    );
  };

  const handleToggleUserLock = (userId: string) => {
    setUsersList((prev) =>
      prev.map((u) =>
        u.id === userId
          ? { ...u, status: u.status === 'active' ? 'locked' : 'active' }
          : u
      )
    );
  };

  const handleRetryJob = (jobId: string) => {
    setJobs((prev) =>
      prev.map((j) =>
        j.id === jobId
          ? {
              ...j,
              status: 'running',
              progress: 20,
              errorReason: undefined,
              duration: '12s (Retrying)',
            }
          : j
      )
    );
    addAuditLog('retry_job', `Admin kích hoạt thử lại tác vụ ${jobId}`, 'EvaluationJob', jobId);
  };

  // If in Auth Suite mode
  if (isAuthMode) {
    return (
      <ToastProvider>
        <AuthShell activeScreen={authScreen} onScreenChange={(s) => setAuthScreen(s)}>
          {authScreen === 'login' && (
            <LoginPage
              onNavigate={(s) => setAuthScreen(s)}
              onLoginSuccess={(user) => {
                const session = user as UserSession;
                setAuthenticatedUser(session);
                if (session?.role) {
                  setActiveRole(session.role);
                }
                setIsAuthMode(false);
              }}
            />
          )}
          {authScreen === 'register' && (
            <RegisterPage onNavigate={(s) => setAuthScreen(s)} />
          )}
          {authScreen === 'forgot-password' && (
            <ForgotPasswordPage onNavigate={(s) => setAuthScreen(s)} />
          )}
          {authScreen === 'verify-email' && (
            <VerifyEmailPage onNavigate={(s) => setAuthScreen(s)} />
          )}
          {authScreen === 'reset-password' && (
            <ResetPasswordPage onNavigate={(s) => setAuthScreen(s)} />
          )}
          {authScreen === 'workspace-success' && (
            <WorkspaceSuccessPage
              user={
                authenticatedUser || {
                  id: 'USR-DEFAULT',
                  email: 'demo@docgrading.vn',
                  fullName: 'Nguyễn Hoàng Minh',
                  role: 'student',
                  accountType: 'student',
                  organization: 'Đại học Bách Khoa Hà Nội',
                  isEmailVerified: true,
                  createdAt: new Date().toISOString(),
                }
              }
              onLogout={() => {
                authService.logout();
                setAuthenticatedUser(null);
                setAuthScreen('login');
              }}
              onNavigate={(s) => setAuthScreen(s)}
              onEnterWorkspace={() => {
                if (authenticatedUser?.role) {
                  setActiveRole(authenticatedUser.role);
                }
                setIsAuthMode(false);
              }}
            />
          )}
        </AuthShell>
      </ToastProvider>
    );
  }

  // Pending counts
  const pendingReviewCount = submissions.filter(
    (s) => s.status === 'needs_review' || s.status === 'pending_approval'
  ).length;
  const pendingAppealCount = appeals.filter((a) => a.status === 'pending').length;

  return (
    <div className="dashboard-shell min-h-screen bg-[#F7F8FA] flex font-sans text-[#172033] antialiased">
      {/* Sidebar */}
      <AppSidebar
        activeRole={activeRole}
        onRoleChange={handleRoleChange}
        currentView={currentView}
        onSelectView={(v) => setCurrentView(v)}
        pendingReviewCount={pendingReviewCount}
        appealCount={pendingAppealCount}
        onOpenAuth={() => setIsAuthMode(true)}
      />

      {/* Right Column: Header + Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen bg-[#F7F8FA]">
        <AppHeader
          activeRole={activeRole}
          currentView={currentView}
          courseTitle={selectedCourse?.name ? `${selectedCourse.code} - ${selectedCourse.name}` : undefined}
          onNavigateBreadcrumb={(v) => setCurrentView(v)}
        />

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto bg-[#F7F8FA]">
          {/* TEACHER VIEWS */}
          {activeRole === 'teacher' && (
            <>
              {currentView === 'teacher_courses' && (
                <CourseListView
                  courses={courses}
                  onSelectCourse={(course) => {
                    setSelectedCourse(course);
                    setCurrentView('teacher_workspace');
                  }}
                  onGoToQueue={(course) => {
                    setSelectedCourse(course);
                    const matchedAsm = assignments.find((a) => a.courseId === course.id);
                    if (matchedAsm) {
                      setSelectedAssignment(matchedAsm);
                    }
                    setCurrentView('teacher_queue');
                  }}
                  onCreateCourse={handleCreateCourse}
                />
              )}

              {currentView === 'teacher_workspace' && (
                <CourseWorkspaceView
                  course={selectedCourse}
                  assignments={assignments}
                  onBack={() => setCurrentView('teacher_courses')}
                  onOpenCreateWizard={() => {
                    setEditingAssignment(null);
                    setShowAssignmentWizard(true);
                  }}
                  onOpenQueue={(asm) => {
                    setSelectedAssignment(asm);
                    setCurrentView('teacher_queue');
                  }}
                  onEditAssignment={(asm) => {
                    setEditingAssignment(asm);
                    setShowAssignmentWizard(true);
                  }}
                />
              )}

              {currentView === 'teacher_queue' && (
                <SubmissionQueueView
                  submissions={submissions}
                  assignments={assignments}
                  selectedAssignmentId={selectedAssignment?.id}
                  onSelectAssignmentFilter={(id) => {
                    const found = assignments.find((a) => a.id === id);
                    if (found) setSelectedAssignment(found);
                  }}
                  onOpenReview={(sub) => {
                    setSelectedSubmission(sub);
                    setCurrentView('teacher_review');
                  }}
                  onBatchPublish={handleBatchPublish}
                />
              )}

              {currentView === 'teacher_review' && (
                <ReviewWorkspaceView
                  submission={selectedSubmission}
                  onBack={() => setCurrentView('teacher_queue')}
                  onApprove={handleApproveSubmission}
                  onPublish={handlePublishSubmission}
                />
              )}

              {currentView === 'teacher_appeals' && (
                <AppealsInboxView
                  appeals={appeals}
                  onRespondAppeal={handleRespondAppeal}
                />
              )}
            </>
          )}

          {/* STUDENT VIEWS */}
          {activeRole === 'student' && (
            <>
              {currentView === 'student_assignments' && (
                <StudentAssignmentsView
                  assignments={assignments.filter((a) => a.status === 'open')}
                  mySubmissions={submissions.filter((s) => s.studentId === currentUser.id)}
                  onOpenUpload={(asm) => {
                    setSelectedAssignment(asm);
                    setCurrentView('student_upload');
                  }}
                  onOpenResult={(sub) => {
                    setSelectedSubmission(sub);
                    setCurrentView('student_result');
                  }}
                  onOpenStatus={(sub) => {
                    setSelectedSubmission(sub);
                    setCurrentView('student_status');
                  }}
                />
              )}

              {currentView === 'student_upload' && (
                <StudentUploadView
                  assignment={selectedAssignment}
                  onBack={() => setCurrentView('student_assignments')}
                  onSubmitSuccess={handleStudentUploadSuccess}
                />
              )}

              {currentView === 'student_status' && (
                <StudentStatusTimelineView
                  submission={selectedSubmission}
                  onBack={() => setCurrentView('student_assignments')}
                  onViewResult={() => setCurrentView('student_result')}
                />
              )}

              {currentView === 'student_result' && (
                <StudentPublishedResultView
                  submission={selectedSubmission}
                  onBack={() => setCurrentView('student_assignments')}
                  onOpenAppeal={() => setShowAppealModal(true)}
                  onOpenCompare={() => setCurrentView('student_compare')}
                />
              )}

              {currentView === 'student_compare' && (
                <VersionCompareView
                  currentSubmission={selectedSubmission}
                  onBack={() => setCurrentView('student_result')}
                />
              )}
            </>
          )}

          {/* ADMIN VIEWS */}
          {activeRole === 'admin' && (
            <>
              {currentView === 'admin_dashboard' && (
                <AdminDashboardView
                  jobs={jobs}
                  auditLogs={auditLogs}
                  onOpenJobs={() => setCurrentView('admin_jobs')}
                  onOpenUsers={() => setCurrentView('admin_users')}
                  onOpenAudit={() => setCurrentView('admin_audit')}
                />
              )}

              {currentView === 'admin_users' && (
                <UserManagementView
                  users={usersList}
                  onUpdateUserRole={handleUpdateUserRole}
                  onToggleUserLock={handleToggleUserLock}
                />
              )}

              {currentView === 'admin_rubrics' && <RubricTemplatesView />}

              {currentView === 'admin_jobs' && (
                <JobMonitoringView jobs={jobs} onRetryJob={handleRetryJob} />
              )}

              {currentView === 'admin_audit' && <AuditLogView logs={auditLogs} />}
            </>
          )}
        </main>
      </div>

      {/* Assignment Wizard Modal */}
      {showAssignmentWizard && (
        <AssignmentWizardModal
          course={selectedCourse}
          initialAssignment={editingAssignment}
          onClose={() => {
            setShowAssignmentWizard(false);
            setEditingAssignment(null);
          }}
          onSaveAssignment={handleSaveAssignment}
        />
      )}

      {/* Student Appeal Modal */}
      {showAppealModal && (
        <AppealModal
          submission={selectedSubmission}
          onClose={() => setShowAppealModal(false)}
          onSubmitAppeal={handleSubmitAppeal}
        />
      )}
    </div>
  );
}
