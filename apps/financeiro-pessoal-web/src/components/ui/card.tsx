import * as React from 'react'

import { cn } from '../../lib/utils'

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-[2rem] border border-[#eadfec] bg-white/78 p-6 shadow-xl shadow-[#341539]/8 backdrop-blur',
        className,
      )}
      {...props}
    />
  )
}
