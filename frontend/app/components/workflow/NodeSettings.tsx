// NodeSettings component renders per-node execution settings: retry behavior, error handling,
// output options, and notes. These settings are stored in node.data._settings and synced via YJS.

import { ChevronDown } from 'lucide-react';

interface NodeSettingsData {
    retryOnFail?: string;       // "true" | "false"
    maxTries?: string;          // "2"-"5"
    waitBetweenTries?: string;  // ms as string "0"-"5000"
    onError?: string;           // "stopWorkflow" | "continueRegularOutput" | "continueErrorOutput"
    alwaysOutputData?: string;  // "true" | "false"
    executeOnce?: string;       // "true" | "false"
    notes?: string;
}

interface NodeSettingsProps {
    settings: NodeSettingsData;
    onChange: (settings: NodeSettingsData) => void;
}

function ToggleRow({ label, description, value, onToggle }: {
    label: string;
    description?: string;
    value: boolean;
    onToggle: () => void;
}) {
    return (
        <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
                <div className="text-xs text-zinc-300">{label}</div>
                {description && <div className="text-[11px] text-zinc-600 mt-0.5 leading-tight">{description}</div>}
            </div>
            <button
                type="button"
                onClick={onToggle}
                className={`relative flex-shrink-0 w-9 h-5 rounded-full transition-colors duration-200 focus:outline-none ${
                    value ? 'bg-indigo-500' : 'bg-white/[0.08]'
                }`}
            >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${
                    value ? 'translate-x-4' : 'translate-x-0'
                }`} />
            </button>
        </div>
    );
}

export function NodeSettings({ settings, onChange }: NodeSettingsProps) {
    const retryOnFail = settings.retryOnFail === 'true';
    const alwaysOutputData = settings.alwaysOutputData === 'true';
    const executeOnce = settings.executeOnce === 'true';

    const update = (patch: Partial<NodeSettingsData>) => onChange({ ...settings, ...patch });

    const inputClasses = "w-full px-3 py-2 text-sm bg-white/[0.02] border border-white/[0.05] rounded-lg text-zinc-300 placeholder:text-zinc-600 focus:outline-none focus:border-white/[0.15] transition-colors";
    const selectClasses = "w-full px-3 py-2 text-sm bg-white/[0.02] border border-white/[0.05] rounded-lg text-zinc-300 focus:outline-none focus:border-white/[0.15] transition-colors appearance-none cursor-pointer";
    const labelClasses = "text-[11px] text-zinc-500 uppercase tracking-wider";

    return (
        <div className="space-y-5">
            {/* Retry on Fail */}
            <div className="space-y-3">
                <ToggleRow
                    label="Retry on Fail"
                    description="Automatically retry this node if it fails"
                    value={retryOnFail}
                    onToggle={() => update({ retryOnFail: retryOnFail ? 'false' : 'true' })}
                />

                {retryOnFail && (
                    <div className="pl-0 space-y-3">
                        <div className="space-y-1.5">
                            <label className={labelClasses}>Max Tries</label>
                            <input
                                type="number"
                                min={2}
                                max={5}
                                value={settings.maxTries ?? '2'}
                                onChange={(e) => update({ maxTries: e.target.value })}
                                className={inputClasses}
                            />
                            <p className="text-[11px] text-zinc-600">Total attempts including the first try (2–5)</p>
                        </div>
                        <div className="space-y-1.5">
                            <label className={labelClasses}>Wait Between Tries (ms)</label>
                            <input
                                type="number"
                                min={0}
                                max={5000}
                                step={100}
                                value={settings.waitBetweenTries ?? '1000'}
                                onChange={(e) => update({ waitBetweenTries: e.target.value })}
                                className={inputClasses}
                            />
                            <p className="text-[11px] text-zinc-600">Milliseconds to wait between retries (0–5000)</p>
                        </div>
                    </div>
                )}
            </div>

            {/* On Error */}
            <div className="space-y-1.5">
                <label className={labelClasses}>On Error</label>
                <div className="relative">
                    <select
                        value={settings.onError ?? 'stopWorkflow'}
                        onChange={(e) => update({ onError: e.target.value })}
                        className={selectClasses}
                    >
                        <option value="stopWorkflow" className="bg-zinc-900">Stop Workflow</option>
                        <option value="continueRegularOutput" className="bg-zinc-900">Continue (Regular Output)</option>
                        <option value="continueErrorOutput" className="bg-zinc-900">Continue (Error Output)</option>
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500 pointer-events-none" />
                </div>
                <p className="text-[11px] text-zinc-600">What to do when all retries are exhausted</p>
            </div>

            <div className="border-t border-white/[0.05]" />

            {/* Always Output Data */}
            <ToggleRow
                label="Always Output Data"
                description="Output an empty item even if the node produces no results"
                value={alwaysOutputData}
                onToggle={() => update({ alwaysOutputData: alwaysOutputData ? 'false' : 'true' })}
            />

            {/* Execute Once */}
            <ToggleRow
                label="Execute Once"
                description="Only process data from the first upstream source"
                value={executeOnce}
                onToggle={() => update({ executeOnce: executeOnce ? 'false' : 'true' })}
            />

            <div className="border-t border-white/[0.05]" />

            {/* Notes */}
            <div className="space-y-1.5">
                <label className={labelClasses}>Notes</label>
                <textarea
                    value={settings.notes ?? ''}
                    onChange={(e) => update({ notes: e.target.value })}
                    placeholder="Add notes about this node..."
                    rows={4}
                    className={`${inputClasses} resize-none`}
                />
            </div>
        </div>
    );
}
