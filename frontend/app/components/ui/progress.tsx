import * as React from 'react';
import * as ProgressPrimitive from '@radix-ui/react-progress';

import { cn } from '~/lib/utils';

type ProgressProps = React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & {
    'data-processing'?: boolean;
};

const Progress = React.forwardRef<
    React.ElementRef<typeof ProgressPrimitive.Root>,
    ProgressProps
>(({ className, value, 'data-processing': dataProcessing, ...props }, ref) => (
    <ProgressPrimitive.Root
        ref={ref}
        className={cn(
            'relative h-2 w-full overflow-hidden rounded-full bg-secondary',
            className
        )}
        {...props}
    >
        <ProgressPrimitive.Indicator
            className={cn(
                'h-full w-full flex-1 bg-white transition-all',
                dataProcessing && 'animate-progress-stripe bg-stripes'
            )}
            style={{ transform: `translateX(-${100 - (value || 0)}%)` }}
        />
    </ProgressPrimitive.Root>
));
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };
