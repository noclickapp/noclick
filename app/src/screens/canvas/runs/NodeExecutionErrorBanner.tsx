import { Node } from '@xyflow/react';
import { AlertTriangle, Sparkles } from 'lucide-react';
import { useSlot } from '@/slots';
import { RUN_FIXES } from '../slots';
import { ErrorActionButton, type ErrorAction } from './ErrorActionButton';
import { parseExecutionError } from './pydanticErrorParser';

interface NodeExecutionErrorBannerProps {
    node: Node;
}

// A failed step's error, shown above its settings: settings the run refused as a list by field, any other failure as
// its text, with the fix the API named for it, if any. "Ask AI" sends the error to the builder beside the canvas, where
// the host has one that listens (`canvas.runs.fixes`).
export function NodeExecutionErrorBanner({ node }: NodeExecutionErrorBannerProps) {
    const { ask } = useSlot(RUN_FIXES);
    if (!node.data?.error) return null;

    const rawError = node.data.error;
    const errorText =
        typeof rawError === 'string'
            ? rawError
            : JSON.stringify(rawError, null, 2);
    const parsedError = parseExecutionError(errorText);
    const errorAction = node.data.errorAction as ErrorAction | undefined;

    const askAi = () => {
        const nodeLabel = node.data?.label || node.id;
        const nodeType = node.type || 'unknown';
        const message = `Help me fix this error in the **${String(nodeLabel)}** node (\`${node.id}\`, type: \`${nodeType}\`):\n\n\`\`\`\n${errorText}\n\`\`\``;
        ask?.(message, node.id);
    };

    return (
        <div className="rounded-xl overflow-hidden border border-red-500/30 bg-red-500/10">
            <div className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border-b border-red-500/20">
                <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400 shrink-0" />
                <span className="text-xs font-semibold text-red-700 dark:text-red-300 uppercase tracking-wider">
                    {parsedError.isValidationError ? 'Configuration Error' : 'Execution Error'}
                </span>
                {ask && (
                    <button
                        type="button"
                        onClick={askAi}
                        className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wider text-red-800 dark:text-red-200 bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 hover:border-red-500/50 transition-colors"
                        title="Send this error to the AI builder for help"
                    >
                        <Sparkles className="h-3 w-3" />
                        <span>Ask AI</span>
                    </button>
                )}
            </div>
            <div className="p-3 space-y-2">
                {parsedError.isValidationError && parsedError.fieldErrors.length > 0 ? (
                    <>
                        <div className="text-sm text-red-800 dark:text-red-200 font-medium">{parsedError.summary}</div>
                        <ul className="space-y-1.5">
                            {parsedError.fieldErrors.map((fieldError, idx) => (
                                <li key={idx} className="flex items-start gap-2 text-sm">
                                    <span className="text-red-600 dark:text-red-400 mt-0.5">•</span>
                                    <span className="text-red-800 dark:text-red-200">
                                        <span className="font-medium text-red-700 dark:text-red-300">{fieldError.fieldName}</span>{' '}
                                        {fieldError.message.replace(fieldError.fieldName + ' ', '')}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </>
                ) : (
                    <pre className="text-sm text-red-800 dark:text-red-200 whitespace-pre-wrap font-mono leading-relaxed max-h-40 overflow-y-auto scrollbar-subtle">
                        {errorText}
                    </pre>
                )}
                {errorAction && (
                    <div className="pt-1">
                        <ErrorActionButton
                            action={errorAction}
                            nodeId={node.id}
                        />
                    </div>
                )}
            </div>
        </div>
    );
}
