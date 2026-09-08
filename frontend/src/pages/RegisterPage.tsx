import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { FormField } from '../components/auth/FormField';
import { PasswordField } from '../components/auth/PasswordField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { PasswordRequirements } from '../components/auth/PasswordRequirements';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { AccountRole, RegisterFullParams } from '../types/auth';
import {
  User,
  Mail,
  Phone,
  Lock,
  GraduationCap,
  BookOpen,
  ShieldAlert,
  CheckCircle2,
  KeyRound,
  IdCard,
  Building,
  School,
  AlertCircle,
  Info,
} from 'lucide-react';

const step1Schema = z
  .object({
    role: z.enum(['student', 'teacher'] as const),
    fullName: z.string().min(2, 'Vui lòng nhập họ và tên (tối thiểu 2 ký tự)'),
    email: z.string().min(1, 'Vui lòng nhập địa chỉ email').email('Email không đúng định dạng'),
    phone: z
      .string()
      .min(10, 'Số điện thoại phải có ít nhất 10 số')
      .regex(/^[0-9+() -]+$/, 'Số điện thoại không hợp lệ'),
    password: z
      .string()
      .min(8, 'Mật khẩu phải có tối thiểu 8 ký tự')
      .regex(/[a-z]/, 'Cần ít nhất một chữ thường')
      .regex(/[A-Z]/, 'Cần ít nhất một chữ hoa')
      .regex(/\d/, 'Cần ít nhất một chữ số')
      .regex(/[^A-Za-z0-9]/, 'Cần ít nhất một ký tự đặc biệt'),
    confirmPassword: z.string().min(1, 'Vui lòng xác nhận mật khẩu'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Mật khẩu xác nhận không khớp',
    path: ['confirmPassword'],
  });

const step2Schema = z
  .object({
    role: z.enum(['student', 'teacher'] as const),
    studentId: z.string().optional(),
    courseClass: z.string().optional(),
    teacherId: z.string().optional(),
    department: z.string().optional(),
    activationCode: z
      .string()
      .min(4, 'Vui lòng nhập mã kích hoạt hoặc mã mời lớp học được cấp'),
    agreeTerms: z.boolean().refine((val) => val === true, {
      message: 'Bạn cần đồng ý với Quy chế & Chính sách bảo mật để tiếp tục',
    }),
  })
  .superRefine((data, ctx) => {
    if (data.role === 'student') {
      if (!data.studentId || data.studentId.trim().length < 4) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['studentId'],
          message: 'Vui lòng nhập Mã số sinh viên (MSSV) hợp lệ',
        });
      }
      if (!data.courseClass || data.courseClass.trim().length < 2) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['courseClass'],
          message: 'Vui lòng nhập Tên lớp hoặc Khóa học sinh hoạt',
        });
      }
    } else if (data.role === 'teacher') {
      if (!data.teacherId || data.teacherId.trim().length < 3) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['teacherId'],
          message: 'Vui lòng nhập Mã cán bộ / Giảng viên hợp lệ',
        });
      }
      if (!data.department || data.department.trim().length < 2) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['department'],
          message: 'Vui lòng nhập Khoa / Bộ môn công tác',
        });
      }
    }
  });

type Step1Values = z.infer<typeof step1Schema>;
type Step2Values = z.infer<typeof step2Schema>;

interface RegisterPageProps {
  onNavigate: (screen: string) => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({ onNavigate }) => {
  const { success } = useToast();
  const [step, setStep] = useState<1 | 2>(1);
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Step 1 Form
  const {
    register: registerStep1,
    handleSubmit: handleStep1Submit,
    watch: watchStep1,
    setValue: setStep1Value,
    formState: { errors: errorsStep1 },
  } = useForm<Step1Values>({
    resolver: zodResolver(step1Schema),
    defaultValues: {
      role: 'student',
      fullName: '',
      email: '',
      phone: '',
      password: '',
      confirmPassword: '',
    },
    mode: 'onTouched',
  });

  const selectedRole = watchStep1('role');
  const currentPassword = watchStep1('password');

  // Step 2 Form
  const {
    register: registerStep2,
    handleSubmit: handleStep2Submit,
    setValue: setStep2Value,
    formState: { errors: errorsStep2 },
  } = useForm<Step2Values>({
    resolver: zodResolver(step2Schema),
    defaultValues: {
      role: 'student',
      studentId: '',
      courseClass: '',
      teacherId: '',
      department: '',
      activationCode: '',
      agreeTerms: false,
    },
    mode: 'onTouched',
  });

  const [step1Data, setStep1Data] = useState<Step1Values | null>(null);

  // Submit Step 1: validate and advance to Step 2
  const onStep1Next = (data: Step1Values) => {
    setServerError(null);
    setStep1Data(data);
    setStep2Value('role', data.role);
    setStep(2);
  };

  // Submit Step 2: finalize registration with activation code
  const onStep2Complete = async (data: Step2Values) => {
    if (!step1Data) {
      setStep(1);
      return;
    }

    setServerError(null);
    setIsSubmitting(true);

    const fullPayload: RegisterFullParams = {
      ...step1Data,
      ...data,
      role: step1Data.role,
    };

    try {
      const response = await authService.register(fullPayload);
      if (response.success) {
        success('Kích hoạt tài khoản thành công! Vui lòng nhập mã OTP để xác minh.');
        authService.setPendingEmail(fullPayload.email);
        onNavigate('verify-email');
      } else {
        setServerError(response.message);
        if (response.errorCode === 'EMAIL_EXISTS') {
          setStep(1);
        }
      }
    } catch {
      setServerError('Kết nối bị gián đoạn. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthFormCard
      backTo={
        step === 2
          ? {
              label: 'Quay lại Bước 1',
              onClick: () => setStep(1),
            }
          : undefined
      }
    >
      {/* Header & Step progress indicator */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[12px] font-semibold text-[#193B64] tracking-wide uppercase">
            Kích hoạt tài khoản
          </span>
          <div className="flex items-center gap-1.5 text-[12px] text-[#667085]">
            <span className="font-semibold text-[#172033]">Bước {step}</span>
            <span>/</span>
            <span>2</span>
            <div className="w-12 h-1.5 bg-[#E2E8F0] rounded-full overflow-hidden ml-1">
              <div
                className={`h-full bg-[#193B64] transition-all duration-300 ${
                  step === 1 ? 'w-1/2' : 'w-full'
                }`}
              />
            </div>
          </div>
        </div>

        <h2 className="text-[22px] sm:text-[24px] font-semibold text-[#172033] tracking-tight">
          {step === 1 ? 'Chọn vai trò & Thông tin' : 'Định danh & Mã ủy quyền'}
        </h2>

        <p className="text-[13px] text-[#667085] mt-1 leading-relaxed">
          {step === 1
            ? 'Hệ thống không mở đăng ký tự do. Vui lòng chọn đúng vai trò được cấp phép.'
            : 'Cung cấp thông tin hồ sơ và mã mời kích hoạt được trường/giảng viên cấp.'}
        </p>
      </div>

      {/* Controlled Registration Notice Banner */}
      <div className="mb-5 p-3 rounded-xl bg-[#EFF5FC] border border-[#D4E4F5] flex items-start gap-2.5 text-[12px] text-[#193B64]">
        <Info className="w-4 h-4 text-[#193B64] shrink-0 mt-0.5" />
        <div className="leading-relaxed">
          <strong>Chính sách phân quyền:</strong> Chỉ người dùng có <strong>Mã mời lớp học</strong> (Sinh viên) hoặc <strong>Mã ủy quyền</strong> (Giảng viên) mới có thể kích hoạt tài khoản.
        </div>
      </div>

      {/* Server error banner */}
      <AuthStatusMessage
        type="error"
        message={serverError}
        onClose={() => setServerError(null)}
      />

      {/* STEP 1: Role Selection & Personal Information */}
      {step === 1 && (
        <form onSubmit={handleStep1Submit(onStep1Next)} noValidate className="space-y-4">
          {/* Role Selection Box */}
          <div>
            <label className="block text-[13px] font-medium text-[#172033] mb-2 select-none">
              Vai trò tài khoản <span className="text-[#C9362B]">*</span>
            </label>

            <div className="space-y-2">
              {/* Student Role Card */}
              <div
                onClick={() => setStep1Value('role', 'student', { shouldValidate: true })}
                className={`p-3 rounded-xl border transition-all cursor-pointer flex items-start gap-3 ${
                  selectedRole === 'student'
                    ? 'border-[#193B64] bg-[#F4F7FB] ring-1 ring-[#193B64]'
                    : 'border-[#D9E0E8] hover:border-[#BFC8D4] bg-white'
                }`}
              >
                <div
                  className={`p-2 rounded-lg shrink-0 mt-0.5 ${
                    selectedRole === 'student' ? 'bg-[#193B64] text-white' : 'bg-[#F0F3F7] text-[#667085]'
                  }`}
                >
                  <GraduationCap className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-semibold text-[#172033]">
                      Sinh viên (Student)
                    </span>
                    {selectedRole === 'student' && (
                      <CheckCircle2 className="w-4 h-4 text-[#193B64]" />
                    )}
                  </div>
                  <p className="text-[12px] text-[#667085] leading-normal mt-0.5">
                    Nộp file báo cáo PDF, theo dõi tiến trình kiểm tra rubric và xem kết quả.
                  </p>
                </div>
              </div>

              {/* Teacher Role Card */}
              <div
                onClick={() => setStep1Value('role', 'teacher', { shouldValidate: true })}
                className={`p-3 rounded-xl border transition-all cursor-pointer flex items-start gap-3 ${
                  selectedRole === 'teacher'
                    ? 'border-[#193B64] bg-[#F4F7FB] ring-1 ring-[#193B64]'
                    : 'border-[#D9E0E8] hover:border-[#BFC8D4] bg-white'
                }`}
              >
                <div
                  className={`p-2 rounded-lg shrink-0 mt-0.5 ${
                    selectedRole === 'teacher' ? 'bg-[#193B64] text-white' : 'bg-[#F0F3F7] text-[#667085]'
                  }`}
                >
                  <BookOpen className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-semibold text-[#172033]">
                      Giảng viên (Teacher)
                    </span>
                    {selectedRole === 'teacher' && (
                      <CheckCircle2 className="w-4 h-4 text-[#193B64]" />
                    )}
                  </div>
                  <p className="text-[12px] text-[#667085] leading-normal mt-0.5">
                    Tạo lớp học, duyệt báo cáo SRS theo rubric và xử lý yêu cầu phúc khảo.
                  </p>
                </div>
              </div>

              {/* Admin Role (Locked / Restricted) Card */}
              <div
                className="p-3 rounded-xl border border-dashed border-[#D9E0E8] bg-[#FAFAFA] flex items-start gap-3 opacity-75 cursor-not-allowed select-none"
                title="Tài khoản Quản trị viên chỉ được cấp trực tiếp bởi Ban Đào tạo"
              >
                <div className="p-2 rounded-lg shrink-0 mt-0.5 bg-[#EAEFF5] text-[#667085]">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-semibold text-[#667085] flex items-center gap-2">
                      Quản trị viên (Admin)
                    </span>
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-[#ECEFF3] text-[#667085] uppercase tracking-wider">
                      Cấp nội bộ
                    </span>
                  </div>
                  <p className="text-[11px] text-[#667085] leading-normal mt-0.5 italic">
                    Không mở đăng ký. Quyền Admin được cấp phát riêng bởi Ban Đào tạo & Quản trị hệ thống.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <FormField
            id="register-fullName"
            label="Họ và tên"
            placeholder={selectedRole === 'student' ? 'Đỗ Minh Trí' : 'TS. Lê Hoàng Nam'}
            leftIcon={<User className="w-4 h-4" />}
            isRequired
            error={errorsStep1.fullName?.message}
            {...registerStep1('fullName')}
          />

          <FormField
            id="register-email"
            label="Địa chỉ email"
            type="email"
            placeholder={
              selectedRole === 'student'
                ? 'student@sis.hust.edu.vn'
                : 'teacher@hust.edu.vn'
            }
            leftIcon={<Mail className="w-4 h-4" />}
            isRequired
            error={errorsStep1.email?.message}
            hint={
              selectedRole === 'student'
                ? 'Khuyến khích sử dụng email sinh viên hoặc email trường cấp.'
                : 'Sử dụng email học thuật hoặc cơ quan để đồng bộ tài khoản giảng viên.'
            }
            {...registerStep1('email')}
          />

          <FormField
            id="register-phone"
            label="Số điện thoại liên hệ"
            type="tel"
            placeholder="0912 345 678"
            leftIcon={<Phone className="w-4 h-4" />}
            isRequired
            error={errorsStep1.phone?.message}
            {...registerStep1('phone')}
          />

          <PasswordField
            id="register-password"
            label="Mật khẩu"
            placeholder="Tối thiểu 8 ký tự"
            isRequired
            error={errorsStep1.password?.message}
            {...registerStep1('password')}
          />

          <PasswordRequirements password={currentPassword} />

          <PasswordField
            id="register-confirmPassword"
            label="Xác nhận mật khẩu"
            placeholder="Nhập lại mật khẩu"
            isRequired
            error={errorsStep1.confirmPassword?.message}
            {...registerStep1('confirmPassword')}
          />

          <div className="pt-2">
            <SubmitButton>Tiếp tục bước xác thực →</SubmitButton>
          </div>
        </form>
      )}

      {/* STEP 2: Role Details & Required Activation Code */}
      {step === 2 && (
        <form onSubmit={handleStep2Submit(onStep2Complete)} noValidate className="space-y-4">
          {/* Active Role Tag */}
          <div className="p-3 rounded-xl bg-[#F4F7FB] border border-[#D9E0E8] flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-[#193B64] text-white flex items-center justify-center">
                {step1Data?.role === 'student' ? (
                  <GraduationCap className="w-4 h-4" />
                ) : (
                  <BookOpen className="w-4 h-4" />
                )}
              </div>
              <div>
                <span className="text-xs text-[#667085] block">Đang kích hoạt vai trò:</span>
                <span className="text-sm font-semibold text-[#172033]">
                  {step1Data?.role === 'student' ? 'Sinh viên (Student)' : 'Giảng viên (Teacher)'}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setStep(1)}
              className="text-xs text-[#193B64] font-medium hover:underline"
            >
              Thay đổi
            </button>
          </div>

          {/* Student Specific Fields */}
          {step1Data?.role === 'student' && (
            <>
              <FormField
                id="register-studentId"
                label="Mã số sinh viên (MSSV)"
                placeholder="Ví dụ: 20214567"
                leftIcon={<IdCard className="w-4 h-4" />}
                isRequired
                error={errorsStep2.studentId?.message}
                {...registerStep2('studentId')}
              />

              <FormField
                id="register-courseClass"
                label="Lớp / Khóa học sinh hoạt"
                placeholder="Ví dụ: Kỹ thuật Phần mềm K66 hoặc INT2208"
                leftIcon={<School className="w-4 h-4" />}
                isRequired
                error={errorsStep2.courseClass?.message}
                {...registerStep2('courseClass')}
              />

              <FormField
                id="register-activationCode"
                label="Mã mời môn học / Lớp (Course Invite Code)"
                placeholder="Ví dụ: SRS-2026 hoặc HUST-K66"
                leftIcon={<KeyRound className="w-4 h-4" />}
                isRequired
                error={errorsStep2.activationCode?.message}
                hint="Nhập mã mời lớp do Giảng viên phụ trách cung cấp (Mã thử nghiệm: SRS-2026)."
                {...registerStep2('activationCode')}
              />
            </>
          )}

          {/* Teacher Specific Fields */}
          {step1Data?.role === 'teacher' && (
            <>
              <FormField
                id="register-teacherId"
                label="Mã cán bộ / Giảng viên (Staff ID)"
                placeholder="Ví dụ: CB-8921"
                leftIcon={<IdCard className="w-4 h-4" />}
                isRequired
                error={errorsStep2.teacherId?.message}
                {...registerStep2('teacherId')}
              />

              <FormField
                id="register-department"
                label="Khoa / Bộ môn công tác"
                placeholder="Ví dụ: Bộ môn Kỹ thuật Phần mềm"
                leftIcon={<Building className="w-4 h-4" />}
                isRequired
                error={errorsStep2.department?.message}
                {...registerStep2('department')}
              />

              <FormField
                id="register-activationCode"
                label="Mã ủy quyền từ Quản trị viên (Admin Token)"
                placeholder="Ví dụ: DOC-ADMIN-2026 hoặc GV-HUST-2026"
                leftIcon={<KeyRound className="w-4 h-4" />}
                isRequired
                error={errorsStep2.activationCode?.message}
                hint="Nhập mã xác thực giảng dạy được cấp bởi Ban Đào tạo (Mã thử nghiệm: DOC-ADMIN-2026)."
                {...registerStep2('activationCode')}
              />
            </>
          )}

          {/* Terms and Academic Integrity Agreement */}
          <div className="pt-2">
            <label className="flex items-start gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                className="w-4 h-4 rounded border-[#D9E0E8] text-[#193B64] focus:ring-[#2C6EBA]/30 accent-[#193B64] mt-0.5"
                {...registerStep2('agreeTerms')}
              />
              <span className="text-[12px] text-[#667085] leading-relaxed">
                Tôi cam kết tuân thủ{' '}
                <a
                  href="#terms"
                  onClick={(e) => e.preventDefault()}
                  className="text-[#193B64] font-medium hover:underline"
                >
                  Quy chế đánh giá báo cáo học thuật
                </a>{' '}
                và{' '}
                <a
                  href="#privacy"
                  onClick={(e) => e.preventDefault()}
                  className="text-[#193B64] font-medium hover:underline"
                >
                  Chính sách liêm chính dữ liệu
                </a>{' '}
                của hệ thống DocGrading.
              </span>
            </label>
            {errorsStep2.agreeTerms?.message && (
              <p className="text-[12px] text-[#C9362B] font-medium mt-1">
                {errorsStep2.agreeTerms.message}
              </p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="w-1/3 h-12 rounded-xl border border-[#D9E0E8] bg-white hover:bg-[#F9FAFC] text-[#172033] text-[14px] font-medium transition-colors"
            >
              Quay lại
            </button>
            <div className="flex-1">
              <SubmitButton isLoading={isSubmitting} loadingText="Đang kích hoạt...">
                Kích hoạt tài khoản
              </SubmitButton>
            </div>
          </div>
        </form>
      )}

      {/* Footer link to Login */}
      <div className="mt-6 pt-5 border-t border-[#D9E0E8] text-center text-[13px] text-[#667085]">
        <span>Đã được cấp tài khoản định danh? </span>
        <button
          type="button"
          onClick={() => onNavigate('login')}
          className="font-semibold text-[#193B64] hover:text-[#102A49] hover:underline transition-colors focus:outline-none"
        >
          Đăng nhập ngay
        </button>
      </div>
    </AuthFormCard>
  );
};
