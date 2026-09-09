import { AuthResponse, LoginParams, UserSession } from '../types/auth';

const STORAGE_KEY = 'rtc_auth_session';

// Simulate network delay for authentic feel (600ms - 900ms)
const delay = (ms = 700) => new Promise((resolve) => setTimeout(resolve, ms));

class AuthService {
  private currentSession: UserSession | null = null;

  constructor() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        this.currentSession = JSON.parse(saved);
      }
    } catch {
      this.currentSession = null;
    }
  }

  getCurrentSession(): UserSession | null {
    return this.currentSession;
  }


  async login({ email, password, rememberMe = true }: LoginParams): Promise<AuthResponse<UserSession>> {
    await delay(750);

    const cleanEmail = email.trim().toLowerCase();

    // Check test scenarios
    if (cleanEmail === 'unverified@rtc.vn') {
      return {
        success: false,
        message: 'Tài khoản chưa được kích hoạt. Vui lòng liên hệ Quản trị viên.',
        errorCode: 'UNVERIFIED_ACCOUNT',
      };
    }

    if (cleanEmail === 'error@rtc.vn') {
      return {
        success: false,
        message: 'Kết nối bị gián đoạn. Vui lòng thử lại.',
        errorCode: 'NETWORK_ERROR',
      };
    }

    // Default test check: password must be at least 6 chars
    if (password === 'wrongpassword' || password.length < 6) {
      return {
        success: false,
        message: 'Email hoặc mật khẩu không chính xác.',
        errorCode: 'INVALID_CREDENTIALS',
      };
    }

    // Stable identities keep prototype data aligned with each workspace.
    let role: 'teacher' | 'student' | 'admin' = 'student';
    let id = 'USR-STUDENT-01';
    let fullName = 'Đỗ Minh Trí';
    let department = 'Kỹ thuật Phần mềm K66';

    if (cleanEmail.includes('admin')) {
      role = 'admin';
      id = 'USR-ADMIN-01';
      fullName = 'Quản trị viên Hệ thống';
      department = 'Ban Đào tạo & Khảo thí';
    } else if (cleanEmail.includes('nam') || cleanEmail.includes('teacher') || cleanEmail.includes('gv')) {
      role = 'teacher';
      id = 'USR-TEACHER-01';
      fullName = 'TS. Lê Hoàng Nam';
      department = 'Bộ môn Kỹ thuật Phần mềm';
    }

    const session: UserSession = {
      id,
      email: cleanEmail,
      fullName,
      phone: '0912 345 678',
      organization: 'Đại học Bách Khoa Hà Nội (HUST)',
      department,
      role,
      accountType: role,
      isEmailVerified: true,
      createdAt: new Date().toISOString(),
    };

    this.currentSession = session;
    if (rememberMe) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    }

    return {
      success: true,
      message: 'Đăng nhập thành công.',
      data: session,
    };
  }


  logout(): void {
    this.currentSession = null;
    localStorage.removeItem(STORAGE_KEY);
  }
}

export const authService = new AuthService();
