// What Resources says about a file: what it is, and the place that keeps it (a workflow, the account, an agent's
// workspace).
import type { FileKind } from '@/lib/embedKind';

export type { FileKind };

/** A workflow, as a list names it beside what it keeps. */
export interface WorkflowRef {
    id: string;
    name: string;
    /** What it's made of, at a glance: the step types its marks are drawn from (its `step_types`). */
    marks: string[];
}

/** An agent step of a workflow. */
export interface AgentRef {
    nodeId: string;
    label: string;
    /** The model or coding harness it runs on. */
    model: string;
}

export type FileSourceKind =
    /** A file a workflow or the account keeps. */
    | 'resources'
    /** An agent's workspace in one of its conversations. */
    | 'workspace'
    /** A named volume. */
    | 'volume'
    /** A builder's own workspace. */
    | 'builder';

export interface FileEntry {
    path: string;
    size: number;
    mtime: string;
    kind: FileKind;
    /** A kept file's id; a workspace's files are addressed by their path. */
    resourceId?: string;
    /** A workspace file's signed path, which its host resolves. */
    urlPath?: string;
    /** A link that reads the file. */
    url?: string | null;
    mime?: string | null;
    resourceType?: string | null;
    /** A table's row count (a table keeps no bytes of its own). */
    rows?: number | null;
    /** A table kept in a database of its own: that database, and its table there. */
    databaseId?: string | null;
    table?: string | null;
}

export interface FileSource {
    id: string;
    kind: FileSourceKind;
    label: string;
    /** Where it is, in one line: "mounted at /workspace". */
    sublabel: string;
    workflow?: WorkflowRef;
    agent?: AgentRef;
    conversationTitle?: string;
    /** A workspace's conversation. */
    conversationKey?: string;
    mount?: string;
    files: FileEntry[];
    truncated?: boolean;
    /** The viewer may upload into and delete from this place. */
    writable?: boolean;
    /** A workspace's signed upload path (edit access only). */
    uploadUrlPath?: string;
}
