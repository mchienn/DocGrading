import React, { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { FormField } from '../components/auth/FormField';
import { SubmitButton } from '../components/auth/SubmitButton';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { Mail, CheckCircle2, RotateCcw } from 'lucide-react';

const forgotPasswordSchema = z.object({
  email: z
    .string()
    .min(1, 'Vui lòng nhập địa chỉ email đã đăng ký')
    .email('Định dạng email không hợp lệ'),
});

type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

interface ForgotPasswordPageProps {
  onNavigate: (screen: string) => void;
}

export const ForgotPasswordPage: React.FC<ForgotPasswordPageProps> = ({ onNavigate }) => {
  const { success } = useToast();
  const [isSuccess, setIsSuccess] = useState(false);
  const [sentEmail, setSentEmail] = useState('');
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [countdown, setCountdown] = useState(0);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: {
      email: authService.getPendingEmail() || '',
    },
  });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (countdown > 0) {
      timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    }
    return () => clearTimeout(timer);
  }, [countdown]);

  const onSubmit = async (data: ForgotPasswordFormValues) => {
    setServerError(null);
    setIsSubmitting(true);
    try {
      const response = await authService.sendPasswordReset(data.email);
      if (response.success) {
        setIsSuccess(true);
        setSentEmail(data.email);
        setCountdown(60);
        success('Đã gửi hướng dẫn khôi phục mật khẩu.');
      } else {
        setServerError(response.message);
      }
    } catch {
      setServerError('Kết nối bị gián đoạn. Vui lòng thử lại.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResend = async () => {
    if (countdown > 0 || !sentEmail) return;
    setIsSubmitting(true);
    try {
      const response = await authService.sendPasswordReset(sentEmail);
      if (response.success) {
        setCountdown(60);
        success('Đã gửi lại liên kết khôi phục mật khẩu.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthFormCard
      backTo={{
        label: 'Quay lại đăng nhập',
        onClick: () => onNavigate('login'),
      }}
    >
      {!isSuccess ? (
        <>
          <div className="mb-6">
            <h2 className="text-[24px] sm:text-[26px] font-semibold text-[#172033] tracking-tight">
              Khôi phục mật khẩu
            </h2>
            <p className="text-[14px] text-[#667085] mt-1.5 leading-relaxed">
              Nhập email liên kết với tài khoản RPA của bạn. Chúng tôi sẽ gửi đường dẫn đặt lại mật khẩu an toàn.
            </p>
          </div>

          <AuthStatusMessage
            type="error"
            message={serverError}
            onClose={() => setServerError(null)}
          />

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            <FormField
              id="forgot-email"
              label="Địa chỉ email đã đăng ký"
              type="email"
              autoComplete="email"
              placeholder="name@company.vn"
              leftIcon={<Mail className="w-4 h-4" />}
              error={errors.email?.message}
              hint="Chúng tôi sẽ gửi liên kết có thời hạn 15 phút"
              isRequired
              {...register('email')}
            />

            <SubmitButton isLoading={isSubmitting} loadingText="Đang gửi yêu cầu...">
              Gửi hướng dẫn khôi phục
            </SubmitButton>
          </form>
        </>
      ) : (
        /* INLINE SUCCESS STATE - No modals per specification */
        <div className="text-left animate-in fade-in duration-200">
          <div className="w-12 h-12 rounded-xl bg-[#F0F9F5] border border-[#CEEADB] flex items-center justify-center text-[#178557] mb-5">
            <CheckCircle2 className="w-6 h-6" strokeWidth={2} />
          </div>

          <h2 className="text-[22px] font-semibold text-[#172033] tracking-tight">
            Kiểm tra hộp thư điện tử
          </h2>

          <p className="text-[14px] text-[#667085] mt-2 leading-relaxed">
            Chúng tôi đã gửi hướng dẫn đặt lại mật khẩu tới địa chỉ:
          </p>

          <div className="my-3.5 p-3 rounded-xl bg-[#F5F7FA] border border-[#D9E0E8] font-mono text-[13px] text-[#193B64] font-semibold flex items-center gap-2">
            <Mail className="w-4 h-4 text-[#667085]" />
            <span className="truncate">{sentEmail}</span>
          </div>

          <p className="text-[13px] text-[#667085] leading-relaxed">
            Nếu không thấy thư trong hộp thư chính, vui lòng kiểm tra thư mục Spam hoặc mục Quảng cáo.
          </p>

          <div className="mt-6 space-y-3">
            <button
              type="button"
              onClick={handleResend}
              disabled={countdown > 0 || isSubmitting}
              className="w-full h-12 rounded-xl border border-[#D9E0E8] bg-white hover:bg-[#F9FAFC] text-[#172033] text-[14px] font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RotateCcw className="w-4 h-4" />
              <span>
                {countdown > 0 ? `Gửi lại sau (${countdown}s)` : 'Gửi lại email khôi phục'}
              </span>
            </button>

            <button
              type="button"
              onClick={() => onNavigate('reset-password')}
              className="w-full h-12 rounded-xl bg-[#193B64] hover:bg-[#102A49] text-white text-[14px] font-medium transition-colors"
            >
              Tiếp tục đặt lại mật khẩu →
            </button>
          </div>
        </div>
      )}

      {/* Footer link to Login */}
      <div className="mt-6 pt-5 border-t border-[#D9E0E8] text-center text-[13px] text-[#667085]">
        <span>Nhớ lại mật khẩu? </span>
        <button
          type="button"
          onClick={() => onNavigate('login')}
          className="font-semibold text-[#193B64] hover:text-[#102A49] hover:underline transition-colors focus:outline-none"
        >
          Quay lại đăng nhập
        </button>
      </div>
    </AuthFormCard>
  );
};
