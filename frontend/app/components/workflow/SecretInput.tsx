import { useState, type InputHTMLAttributes } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '~/lib/utils';

interface SecretInputProps extends InputHTMLAttributes<HTMLInputElement> {
    inputClassName?: string;
}

export function SecretInput({ className, inputClassName, ...props }: SecretInputProps) {
    const [isVisible, setIsVisible] = useState(false);

    return (
        <div className={cn('relative', className)}>
            <input
                {...props}
                type={isVisible ? 'text' : 'password'}
                className={cn(inputClassName, 'pr-10')}
            />
            <button
                type="button"
                onClick={() => setIsVisible((visible) => !visible)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-500 transition-colors hover:text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-700"
                aria-label={isVisible ? 'Hide secret' : 'Show secret'}
                title={isVisible ? 'Hide secret' : 'Show secret'}
            >
                {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
        </div>
    );
}
