import {
  AuthResponse,
  LoginParams,
  RegisterFullParams,
  ResetPasswordParams,
  UserSession,
  VerifyEmailParams,
} from '../types/auth';

const STORAGE_KEY = 'rtc_auth_session';
const PENDING_EMAIL_KEY = 'rtc_pending_verification_email';

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

  getPendingEmail(): string {
    return localStorage.getItem(PENDING_EMAIL_KEY) || 'nguyenvana@rtc.vn';
  }

  setPendingEmail(email: string): void {
    localStorage.setItem(PENDING_EMAIL_KEY, email);
  }

  async login({ email, password, rememberMe = true }: LoginParams): Promise<AuthResponse<UserSession>> {
    await delay(750);

    const cleanEmail = email.trim().toLowerCase();

    // Check test scenarios
    if (cleanEmail === 'unverified@rtc.vn') {
      return {
        success: false,
        message: 'Tài khoản này chưa được xác minh.',
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

    // Role determination based on account or credentials
    let role: 'teacher' | 'student' | 'admin' = 'student';
    let fullName = 'Đỗ Minh Trí';
    let department = 'Kỹ thuật Phần mềm K66';

    if (cleanEmail.includes('admin')) {
      role = 'admin';
      fullName = 'Quản trị viên Hệ thống';
      department = 'Ban Đào tạo & Khảo thí';
    } else if (cleanEmail.includes('nam') || cleanEmail.includes('teacher') || cleanEmail.includes('gv')) {
      role = 'teacher';
      fullName = 'TS. Lê Hoàng Nam';
      department = 'Bộ môn Kỹ thuật Phần mềm';
    }

    const session: UserSession = {
      id: 'USR-' + Math.random().toString(36).substring(2, 9).toUpperCase(),
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

  async loginWithGoogle(): Promise<AuthResponse<UserSession>> {
    await delay(850);

    const session: UserSession = {
      id: 'USR-GGL-' + Math.random().toString(36).substring(2, 7).toUpperCase(),
      email: 'minh.nguyen@gmail.com',
      fullName: 'Minh Nguyễn (Google)',
      organization: 'HUST - DocGrading',
      role: 'student',
      accountType: 'student',
      isEmailVerified: true,
      createdAt: new Date().toISOString(),
    };

    this.currentSession = session;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));

    return {
      success: true,
      message: 'Đăng nhập bằng tài khoản Google thành công.',
      data: session,
    };
  }

  async register(params: RegisterFullParams): Promise<AuthResponse<UserSession>> {
    await delay(800);

    const cleanEmail = params.email.trim().toLowerCase();

    if (cleanEmail === 'exists@hust.edu.vn' || cleanEmail === 'nam.lehoang@hust.edu.vn') {
      return {
        success: false,
        message: 'Email đã được đăng ký trên hệ thống DocGrading.',
        errorCode: 'EMAIL_EXISTS',
      };
    }

    const code = params.activationCode.trim().toUpperCase();
    if (code === 'INVALID' || code === 'EXPIRED' || code.length < 4) {
      return {
        success: false,
        message: 'Mã kích hoạt/ủy quyền không hợp lệ hoặc đã hết hạn. Vui lòng liên hệ Giảng viên hoặc Ban Đào tạo.',
        errorCode: 'INVALID_INVITATION_CODE',
      };
    }

    const role = params.role === 'teacher' ? 'teacher' : 'student';
    const department =
      params.role === 'teacher'
        ? params.department || 'Bộ môn Kỹ thuật Phần mềm'
        : params.courseClass || 'Kỹ thuật Phần mềm K66';

    const session: UserSession = {
      id: 'USR-' + Math.random().toString(36).substring(2, 9).toUpperCase(),
      email: cleanEmail,
      fullName: params.fullName.trim(),
      phone: params.phone.trim(),
      organization: 'Đại học Bách Khoa Hà Nội (HUST)',
      department,
      studentId: params.studentId,
      teacherId: params.teacherId,
      role,
      accountType: role,
      isEmailVerified: false,
      createdAt: new Date().toISOString(),
    };

    this.setPendingEmail(cleanEmail);

    return {
      success: true,
      message: 'Kích hoạt tài khoản thành công. Vui lòng xác minh địa chỉ email của bạn.',
      data: session,
    };
  }

  async sendPasswordReset(email: string): Promise<AuthResponse<{ sentTo: string }>> {
    await delay(700);

    const cleanEmail = email.trim().toLowerCase();
    if (cleanEmail === 'error@rtc.vn') {
      return {
        success: false,
        message: 'Kết nối bị gián đoạn. Vui lòng thử lại.',
        errorCode: 'NETWORK_ERROR',
      };
    }

    this.setPendingEmail(cleanEmail);

    return {
      success: true,
      message: 'Liên kết đặt lại mật khẩu đã được gửi đến hộp thư của bạn.',
      data: { sentTo: cleanEmail },
    };
  }

  async verifyEmail({ email, code }: VerifyEmailParams): Promise<AuthResponse<UserSession>> {
    await delay(750);

    if (code === '000000') {
      return {
        success: false,
        message: 'Mã xác minh đã hết hạn.',
        errorCode: 'CODE_EXPIRED',
      };
    }

    if (code !== '123456' && code !== '888888') {
      return {
        success: false,
        message: 'Mã xác minh không chính xác. Vui lòng kiểm tra lại.',
        errorCode: 'INVALID_CODE',
      };
    }

    const session: UserSession = {
      id: 'USR-VERIFIED-' + Math.random().toString(36).substring(2, 7).toUpperCase(),
      email,
      fullName: 'Người dùng DocGrading',
      role: 'student',
      accountType: 'student',
      isEmailVerified: true,
      createdAt: new Date().toISOString(),
    };

    this.currentSession = session;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));

    return {
      success: true,
      message: 'Xác minh tài khoản thành công.',
      data: session,
    };
  }

  async resendOtp(email: string): Promise<AuthResponse<{ nextAllowedInSeconds: number }>> {
    await delay(500);

    return {
      success: true,
      message: `Mã xác minh mới đã được gửi tới ${email}.`,
      data: { nextAllowedInSeconds: 60 },
    };
  }

  async resetPassword({ newPassword }: ResetPasswordParams): Promise<AuthResponse<boolean>> {
    await delay(800);

    if (newPassword.length < 8) {
      return {
        success: false,
        message: 'Mật khẩu chưa đáp ứng tiêu chuẩn an toàn.',
        errorCode: 'INVALID_CREDENTIALS',
      };
    }

    return {
      success: true,
      message: 'Cập nhật mật khẩu thành công. Bạn có thể đăng nhập bằng mật khẩu mới.',
      data: true,
    };
  }

  logout(): void {
    this.currentSession = null;
    localStorage.removeItem(STORAGE_KEY);
  }
}

export const authService = new AuthService();
