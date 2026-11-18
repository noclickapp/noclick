import { cn } from '@/ui/utils';
import { CodeText } from './Code';
import { CODE_SURFACE } from './CodeSnippet';
import { CopyButton } from './CopyButton';

/** Pretty-printed JSON, coloured like the console's code, copyable as plain text. */
export function JsonView({ value, className }: { value: unknown; className?: string }) {
    const text = value === undefined ? 'undefined' : JSON.stringify(value, null, 2);
    return (
        <div className={cn('relative', CODE_SURFACE, className)}>
            <CopyButton value={text} label="Copy JSON" className="absolute right-1.5 top-1.5" />
            <pre className="m-0 max-h-[480px] overflow-auto px-3.5 py-3 pr-9 font-mono text-[12px] leading-relaxed text-foreground/90">
                <CodeText code={text} language={value === undefined ? undefined : 'json'} />
            </pre>
        </div>
    );
}
