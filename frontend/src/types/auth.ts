import { UserRole } from './docgrading';

export type AccountRole = 'student' | 'teacher';

export interface UserSession {
  id: string;
  email: string;
  fullName: string;
  phone?: string;
  organization?: string;
  department?: string;
  studentId?: string;
  teacherId?: string;
  role: UserRole;
  accountType?: string;
  avatarUrl?: string;
  isEmailVerified: boolean;
  createdAt: string;
}

export interface AuthResponse<T = unknown> {
  success: boolean;
  message: string;
  data?: T;
  errorCode?:
    | 'INVALID_CREDENTIALS'
    | 'UNVERIFIED_ACCOUNT'
    | 'EMAIL_EXISTS'
    | 'CODE_EXPIRED'
    | 'NETWORK_ERROR'
    | 'INVALID_CODE'
    | 'INVALID_INVITATION_CODE';
}

export interface LoginParams {
  email: string;
  password: string;
  rememberMe?: boolean;
}

export interface RegisterStep1Params {
  role: AccountRole;
  fullName: string;
  email: string;
  phone: string;
  password: string;
  confirmPassword: string;
}

export interface RegisterStep2Params {
  role: AccountRole;
  studentId?: string;
  courseClass?: string;
  teacherId?: string;
  department?: string;
  activationCode: string;
  agreeTerms: boolean;
}

export type RegisterFullParams = RegisterStep1Params & RegisterStep2Params;

export interface VerifyEmailParams {
  email: string;
  code: string;
}

export interface ResetPasswordParams {
  email: string;
  code?: string;
  newPassword: string;
  confirmPassword: string;
}
