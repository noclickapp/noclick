/**
 * SkillRowExpansion — inline content shown beneath a skill row when expanded.
 * Lazily fetches the full skill detail (skill:get) on first expansion and
 * renders body_text + a constrained ReadOnlyFlowCanvas preview of the workflow.
 * Visual treatment matches the SkillsList white/[0.0X] palette so the row +
 * expansion read as a single unified card.
 */

import { useEffect, useState } from 'react';
import { FileText, Workflow as WorkflowIcon } from 'lucide-react';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { ReadOnlyFlowCanvas } from '~/components/workflow/ReadOnlyFlowCanvas';
import type { Node, Edge } from '@xyflow/react';
import type { SkillDetail } from './skillTypes';

const PREVIEW_HEIGHT_PX = 320;
const TEXT_PREVIEW_CHAR_LIMIT = 1200;

export function SkillRowExpansion({ skillId, onOpenEditor }: { skillId: string; onOpenEditor: () => void }) {
    const [detail, setDetail] = useState<SkillDetail | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        setLoading(true);
        setError(null);
        sendEventWithCallback(
            { event_name: 'skill:get', skill_id: skillId } as any,
            (resp: any) => {
                setLoading(false);
                if (resp?.error) {
                    setError(resp.error);
                    return;
                }
                setDetail(resp.skill as SkillDetail);
            },
        );
    }, [skillId]);

    if (loading) {
        return <div className="px-4 py-2 text-[11px] text-muted-foreground/70 dark:text-white/30 border-x border-b border-border dark:border-white/[0.06] rounded-b-xl bg-foreground/[0.02]">Loading…</div>;
    }
    if (error) {
        return <div className="px-4 py-2 text-[11px] text-red-700 dark:text-red-300 border-x border-b border-border dark:border-white/[0.06] rounded-b-xl bg-red-50 dark:bg-red-950/20">{error}</div>;
    }
    if (!detail) return null;

    const text = detail.body_text || '';
    const truncatedText = text.length > TEXT_PREVIEW_CHAR_LIMIT ? text.slice(0, TEXT_PREVIEW_CHAR_LIMIT) + '…' : text;
    const wf = detail.body_workflow;
    const nodes: Node[] = Array.isArray(wf?.nodes) ? (wf.nodes as Node[]) : [];
    const edges: Edge[] = Array.isArray(wf?.edges) ? (wf.edges as Edge[]) : [];
    const hasContent = !!truncatedText || nodes.length > 0;

    return (
        <div className="border-x border-b border-border dark:border-white/[0.06] rounded-b-xl bg-background/40 divide-y divide-border dark:divide-white/[0.06]">
            {!hasContent && (
                <div className="flex items-center justify-between px-4 py-3 text-[12px] text-muted-foreground dark:text-white/40">
                    <span>No content yet — open the editor to add a description, text, or workflow.</span>
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            onOpenEditor();
                        }}
                        className="px-2 py-1 text-[11px] font-medium bg-foreground/[0.05] border border-border dark:border-white/[0.08] hover:bg-foreground/[0.08] hover:border-muted-foreground/30 dark:hover:border-white/[0.12] text-foreground/80 rounded-lg transition-colors"
                    >
                        Open editor
                    </button>
                </div>
            )}
            {truncatedText && (
                <ExpansionPanel icon={FileText} label="Text body">
                    <pre className="text-[11px] text-foreground/80 leading-relaxed whitespace-pre-wrap font-mono px-4 py-3 max-h-[260px] overflow-auto scrollbar-subtle">
                        {truncatedText}
                    </pre>
                </ExpansionPanel>
            )}
            {nodes.length > 0 && (
                <ExpansionPanel
                    icon={WorkflowIcon}
                    label={`Workflow (${nodes.length} ${nodes.length === 1 ? 'node' : 'nodes'}, ${edges.length} ${edges.length === 1 ? 'edge' : 'edges'})`}
                >
                    <div
                        style={{ height: PREVIEW_HEIGHT_PX }}
                        className="relative overflow-hidden bg-[hsl(var(--canvas-bg))]"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <ReadOnlyFlowCanvas nodes={nodes} edges={edges} isEmbed />
                    </div>
                </ExpansionPanel>
            )}
        </div>
    );
}

function ExpansionPanel({
    icon: Icon,
    label,
    children,
}: {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
    children: React.ReactNode;
}) {
    return (
        <div>
            <div className="flex items-center gap-2 px-4 py-1.5 bg-foreground/[0.02]">
                <Icon className="h-3 w-3 text-muted-foreground dark:text-white/40" />
                <span className="text-[10px] font-medium text-muted-foreground dark:text-white/40 uppercase tracking-wide">{label}</span>
            </div>
            {children}
        </div>
    );
}
