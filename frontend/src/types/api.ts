import type { components } from '../api/schema';

export type ApiUser = components['schemas']['UserResponse'];
export type ApiCourse = components['schemas']['CourseResponse'];
export type ApiAssignment = components['schemas']['AssignmentResponse'];
export type ApiRubric = components['schemas']['RubricVersionResponse'];
export type ApiCriterion = components['schemas']['CriterionResponse'];
export type ApiJob = components['schemas']['AnalysisJobResponse'];
export type ApiPresign = components['schemas']['PresignResponse'];
export type ApiCompletion = components['schemas']['CompletionResponse'];
export type WorkspaceRole = 'admin' | 'teacher' | 'student';

export function strongestRole(roles: string[]): WorkspaceRole {
  if (roles.includes('ADMIN')) return 'admin';
  if (roles.includes('TEACHER')) return 'teacher';
  return 'student';
}
