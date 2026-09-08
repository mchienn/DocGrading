import React from 'react';
import { Check, Dot } from 'lucide-react';

interface PasswordRequirementsProps {
  password?: string;
  className?: string;
}

export const PasswordRequirements: React.FC<PasswordRequirementsProps> = ({
  password = '',
  className = '',
}) => {
  const rules = [
    {
      id: 'length',
      label: 'Tối thiểu 8 ký tự',
      isValid: password.length >= 8,
    },
    {
      id: 'cases',
      label: 'Chữ hoa và chữ thường',
      isValid: /[a-z]/.test(password) && /[A-Z]/.test(password),
    },
    {
      id: 'number',
      label: 'Ít nhất 1 chữ số',
      isValid: /\d/.test(password),
    },
    {
      id: 'special',
      label: 'Ký tự đặc biệt (@, #, $, %...)',
      isValid: /[^A-Za-z0-9]/.test(password),
    },
  ];

  return (
    <div className={`p-3 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] ${className}`}>
      <p className="text-[12px] font-medium text-[#172033] mb-2">
        Yêu cầu mật khẩu an toàn:
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
        {rules.map((rule) => (
          <div
            key={rule.id}
            className={`flex items-center gap-1.5 text-[12px] transition-colors duration-150 ${
              rule.isValid ? 'text-[#178557] font-medium' : 'text-[#667085]'
            }`}
          >
            {rule.isValid ? (
              <Check className="w-3.5 h-3.5 text-[#178557] flex-shrink-0" strokeWidth={2.5} />
            ) : (
              <Dot className="w-4 h-4 text-[#A0AEC0] flex-shrink-0 -mx-0.5" />
            )}
            <span>{rule.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
