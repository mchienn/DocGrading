import React, { forwardRef, useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { FormField, FormFieldProps } from './FormField';

export interface PasswordFieldProps extends Omit<FormFieldProps, 'type' | 'rightElement'> {
  showStrength?: boolean;
}

export const PasswordField = forwardRef<HTMLInputElement, PasswordFieldProps>(
  ({ label = 'Mật khẩu', ...props }, ref) => {
    const [showPassword, setShowPassword] = useState(false);

    return (
      <FormField
        ref={ref}
        label={label}
        type={showPassword ? 'text' : 'password'}
        rightElement={
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setShowPassword(!showPassword)}
            className="text-[#667085] hover:text-[#172033] p-1 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-[#2C6EBA]/30"
            aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
            title={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
          >
            {showPassword ? (
              <EyeOff className="w-4 h-4" strokeWidth={1.75} />
            ) : (
              <Eye className="w-4 h-4" strokeWidth={1.75} />
            )}
          </button>
        }
        {...props}
      />
    );
  }
);

PasswordField.displayName = 'PasswordField';
