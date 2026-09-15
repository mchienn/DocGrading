export interface Course {
  id: string;
  code: string;
  name: string;
  semester: string;
  studentCount: number;
  assignmentCount: number;
  activeAssignments: number;
  pendingReviews: number;
  inviteCode?: string;
  credits?: number;
  department?: string;
  rubricStandard?: string;
  gradedCount?: number;
  status?: 'active' | 'archived';
}

export interface AssignmentRequirements {
  allowedFormat: 'PDF';
  maxFileSizeMb: number;
  minPages?: number;
  maxPages?: number;
  textLayerRequired: boolean;
  templateProvided?: boolean;
}

export interface RubricCriterion {
  id: string;
  code: string;
  name: string;
  description: string;
  weight: number; // percentage (sum must be 100)
  maxLevel: number; // standard 4
  defaultEvaluator: 'Rule-Engine' | 'LLM-Evaluator' | 'Hybrid-IR';
  evidenceRequired: boolean;
}

export type SubmissionStatus =
  | 'received'
  | 'checking_pdf'
  | 'queued'
  | 'evaluating'
  | 'needs_review'
  | 'pending_approval'
  | 'approved'
  | 'published'
  | 'error'
  | 'resubmit_requested';

export interface Finding {
  id: string;
  criterionId: string;
  severity: 'critical' | 'major' | 'minor' | 'info';
  title: string;
  description: string;
  suggestion: string;
  pageNumber: number;
  section: string;
  snippet: string;
  status: 'accepted' | 'rejected' | 'modified';
  confidence: number;
}

export interface CriterionResult {
  criterionId: string;
  criterionName: string;
  weight: number;
  proposedLevel: number; // 0 to 4
  confirmedLevel: number; // 0 to 4
  overrideReason?: string;
  findings: Finding[];
  teacherNotes?: string;
}

export interface PdfPageContent {
  pageNumber: number;
  title: string;
  content: string[];
  findingsOnPage?: string[]; // finding IDs
}

export interface Submission {
  id: string;
  assignmentId: string;
  assignmentTitle: string;
  courseCode: string;
  studentId: string;
  studentName: string;
  studentCode: string;
  version: number;
  fileName: string;
  fileSize: string;
  pageCount: number;
  submittedAt: string;
  status: SubmissionStatus;
  proposedScore: number; // 0 - 100
  finalScore?: number; // 0 - 100
  confidence: number; // 0 - 1
  reviewerId?: string;
  reviewerName?: string;
  reviewedAt?: string;
  publishedAt?: string;
  criteriaResults: CriterionResult[];
  pages: PdfPageContent[];
}

export interface Assignment {
  id: string;
  courseId: string;
  courseCode: string;
  courseName: string;
  title: string;
  description: string;
  dueDate: string;
  maxSubmissions: number;
  status: 'draft' | 'open' | 'closed';
  submittedCount: number;
  reviewedCount: number;
  publishedCount: number;
  rubricId: string;
  requirements: AssignmentRequirements;
  criteria: RubricCriterion[];
}
