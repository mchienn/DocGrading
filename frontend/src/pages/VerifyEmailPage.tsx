import React, { useState, useEffect } from 'react';
import { AuthFormCard } from '../components/auth/AuthFormCard';
import { OtpInput } from '../components/auth/OtpInput';
import { SubmitButton } from '../components/auth/SubmitButton';
import { AuthStatusMessage } from '../components/auth/AuthStatusMessage';
import { useToast } from '../components/auth/Toast';
import { authService } from '../services/authService';
import { Mail, RotateCcw, CheckCircle2, ShieldCheck, ArrowRight } from 'lucide-react';

interface VerifyEmailPageProps {
  onNavigate: (screen: string) => void;
  onVerifySuccess?: () => void;
}

export const VerifyEmailPage: React.FC<VerifyEmailPageProps> = ({
  onNavigate,
  onVerifySuccess,
}) => {
  const { success, error: toastError } = useToast();
  const [code, setCode] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{
    type: 'error' | 'success';
    text: string;
  } | null>(null);
  const [countdown, setCountdown] = useState(45);
  const [email, setEmail] = useState(() => authService.getPendingEmail());

  // Mask email helper (e.g. nguyenvana@rtc.vn -> ng***a@rtc.vn)
  const maskEmail = (raw: string) => {
    if (!raw.includes('@')) return raw;
    const [name, domain] = raw.split('@');
    if (name.length <= 2) return `${name}***@${domain}`;
    const first2 = name.slice(0, 2);
    const last1 = name.slice(-1);
    return `${first2}***${last1}@${domain}`;
  };

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (countdown > 0) {
      timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    }
    return () => clearTimeout(timer);
  }, [countdown]);

  const handleVerify = async (otpCode = code) => {
    if (otpCode.length !== 6) {
      setStatusMessage({
        type: 'error',
        text: 'Vui lòng nhập đầy đủ 6 chữ số mã OTP.',
      });
      return;
    }

    setStatusMessage(null);
    setIsVerifying(true);

    try {
      const response = await authService.verifyEmail({ email, code: otpCode });
      if (response.success) {
        setIsSuccess(true);
        success('Xác minh địa chỉ email thành công!');
        onVerifySuccess?.();
      } else {
        setStatusMessage({
          type: 'error',
          text: response.message,
        });
      }
    } catch {
      setStatusMessage({
        type: 'error',
        text: 'Kết nối bị gián đoạn. Vui lòng thử lại.',
      });
    } finally {
      setIsVerifying(false);
    }
  };

  const handleResend = async () => {
    if (countdown > 0 || isVerifying) return;
    try {
      const res = await authService.resendOtp(email);
      if (res.success) {
        setCountdown(60);
        setCode('');
        setStatusMessage(null);
        success(`Mã OTP mới đã được gửi tới ${email}.`);
      }
    } catch {
      toastError('Không thể gửi lại mã xác minh. Vui lòng thử lại sau.');
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
          {/* Header */}
          <div className="mb-6">
            <div className="w-10 h-10 rounded-xl bg-[#193B64]/10 border border-[#193B64]/20 flex items-center justify-center text-[#193B64] mb-3.5">
              <Mail className="w-5 h-5" />
            </div>

            <h2 className="text-[24px] sm:text-[26px] font-semibold text-[#172033] tracking-tight">
              Xác minh địa chỉ email
            </h2>

            <p className="text-[14px] text-[#667085] mt-1.5 leading-relaxed">
              Mã bảo mật gồm 6 chữ số đã được gửi đến:{' '}
              <span className="font-semibold text-[#172033]">{maskEmail(email)}</span>
            </p>
          </div>

          {/* Status Message */}
          <AuthStatusMessage
            type={statusMessage?.type || 'error'}
            message={statusMessage?.text || null}
            onClose={() => setStatusMessage(null)}
          />

          {/* OTP Input Component */}
          <div className="space-y-5 my-6">
            <div>
              <label className="block text-[13px] font-medium text-[#172033] mb-3 text-left">
                Nhập mã xác thực OTP
              </label>
              <OtpInput
                value={code}
                onChange={setCode}
                hasError={statusMessage?.type === 'error'}
                disabled={isVerifying}
                onComplete={(completedCode) => handleVerify(completedCode)}
              />
            </div>

            {/* Resend Countdown */}
            <div className="flex items-center justify-between text-[13px] text-[#667085] pt-1">
              <span>Chưa nhận được mã?</span>
              <button
                type="button"
                onClick={handleResend}
                disabled={countdown > 0 || isVerifying}
                className="inline-flex items-center gap-1.5 font-medium text-[#2C6EBA] hover:text-[#193B64] hover:underline disabled:text-[#667085]/60 disabled:no-underline disabled:cursor-not-allowed focus:outline-none transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>{countdown > 0 ? `Gửi lại sau ${countdown}s` : 'Gửi lại mã'}</span>
              </button>
            </div>

            <SubmitButton
              onClick={() => handleVerify()}
              isLoading={isVerifying}
              loadingText="Đang kiểm tra mã OTP..."
              disabled={code.length !== 6}
            >
              Xác minh tài khoản
            </SubmitButton>
          </div>
        </>
      ) : (
        /* SUCCESS CONFIRMATION STATE */
        <div className="text-left animate-in fade-in duration-200">
          <div className="w-12 h-12 rounded-xl bg-[#F0F9F5] border border-[#CEEADB] flex items-center justify-center text-[#178557] mb-5">
            <CheckCircle2 className="w-6 h-6" strokeWidth={2} />
          </div>

          <h2 className="text-[22px] font-semibold text-[#172033] tracking-tight">
            Xác minh tài khoản thành công!
          </h2>

          <p className="text-[14px] text-[#667085] mt-2 leading-relaxed">
            Hộp thư <span className="font-semibold text-[#172033]">{email}</span> đã được liên kết và kích hoạt chính sách bảo mật cho toàn bộ dịch vụ RPA.
          </p>

          <div className="mt-6 space-y-3">
            <button
              type="button"
              onClick={() => onNavigate('login')}
              className="w-full h-12 rounded-xl bg-[#193B64] hover:bg-[#102A49] text-white text-[14px] font-medium flex items-center justify-center gap-2 transition-colors shadow-sm"
            >
              <span>Tiến hành đăng nhập vào RPA</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Footer support */}
      <div className="mt-6 pt-5 border-t border-[#D9E0E8] text-center text-[13px] text-[#667085]">
        <span>Cần hỗ trợ xác thực? </span>
        <a
          href="#support"
          onClick={(e) => e.preventDefault()}
          className="font-semibold text-[#193B64] hover:underline"
        >
          Liên hệ Quản trị viên
        </a>
      </div>
    </AuthFormCard>
  );
};
