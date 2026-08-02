import * as React from 'react'

import { cn } from '../../lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'h-12 w-full rounded-2xl border border-[#eadfec] bg-white/80 px-4 text-sm text-[#19151d] shadow-sm outline-none transition placeholder:text-[#8d8292] focus:border-[#83358F] focus:ring-4 focus:ring-[#83358F]/10',
        className,
      )}
      {...props}
    />
  ),
)
Input.displayName = 'Input'
