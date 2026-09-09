import { UserRole } from './docgrading';

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
  errorCode?: 'INVALID_CREDENTIALS' | 'UNVERIFIED_ACCOUNT' | 'NETWORK_ERROR';
}

export interface LoginParams {
  email: string;
  password: string;
  rememberMe?: boolean;
}
