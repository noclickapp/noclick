// Attachment-tray state for chat composers: accepts files from the picker,
// paste, or drag-drop, uploads them to R2 immediately (useResourceUpload), and
// exposes the ready set for the send payload. Added for the agent chat
// interface's image/file attachments; reusable by any chat surface scoped to a
// workflow + node.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import type { AgentChatAttachment } from '~/lib/agentChat';

export interface PendingChatAttachment {
    localId: string;
    name: string;
    mimeType: string;
    sizeBytes: number;
    /** Object URL for the local image thumbnail while uploading (and after —
     *  the tray keeps showing the local pixels rather than refetching R2). */
    previewUrl?: string;
    status: 'uploading' | 'ready' | 'error';
    /** Byte fraction 0..1 of the in-flight upload (only while status === 'uploading'). */
    progress?: number;
    error?: string;
    /** Set once status === 'ready' — what the send payload carries. */
    uploaded?: AgentChatAttachment;
}

let nextLocalId = 0;

export function useChatAttachments(
    workflowId: string | undefined,
    nodeId: string
) {
    const { uploadFile } = useResourceUpload();
    const [attachments, setAttachments] = useState<PendingChatAttachment[]>([]);

    // Object URLs leak until revoked; revoke everything still minted on
    // unmount (remove/clear revoke eagerly).
    const previewUrlsRef = useRef<Set<string>>(new Set());
    useEffect(
        () => () => {
            previewUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
        },
        []
    );

    const addFiles = useCallback(
        (files: File[] | FileList) => {
            if (!workflowId) return;
            for (const file of Array.from(files)) {
                const localId = `chat-att-${nextLocalId++}`;
                const previewUrl = file.type.startsWith('image/')
                    ? URL.createObjectURL(file)
                    : undefined;
                if (previewUrl) previewUrlsRef.current.add(previewUrl);
                setAttachments((prev) =>
                    prev.concat({
                        localId,
                        name: file.name || 'pasted-image.png',
                        mimeType: file.type || 'application/octet-stream',
                        sizeBytes: file.size,
                        previewUrl,
                        status: 'uploading',
                        progress: 0,
                    })
                );
                uploadFile(file, workflowId, nodeId, (fraction) =>
                    setAttachments((prev) =>
                        prev.map((a) =>
                            a.localId === localId && a.status === 'uploading'
                                ? { ...a, progress: fraction }
                                : a
                        )
                    )
                ).then(
                    (res) =>
                        setAttachments((prev) =>
                            prev.map((a) =>
                                a.localId === localId
                                    ? {
                                          ...a,
                                          status: 'ready',
                                          uploaded: {
                                              resourceId: res.resourceId,
                                              url: res.publicUrl,
                                              name: a.name,
                                              mimeType: res.mimeType,
                                              sizeBytes: res.sizeBytes,
                                          },
                                      }
                                    : a
                            )
                        ),
                    (err: unknown) =>
                        setAttachments((prev) =>
                            prev.map((a) =>
                                a.localId === localId
                                    ? {
                                          ...a,
                                          status: 'error',
                                          error:
                                              err instanceof Error
                                                  ? err.message
                                                  : 'Upload failed',
                                      }
                                    : a
                            )
                        )
                );
            }
        },
        [workflowId, nodeId, uploadFile]
    );

    const revoke = useCallback((a: PendingChatAttachment) => {
        if (a.previewUrl) {
            URL.revokeObjectURL(a.previewUrl);
            previewUrlsRef.current.delete(a.previewUrl);
        }
    }, []);

    const removeAttachment = useCallback(
        (localId: string) => {
            setAttachments((prev) => {
                const target = prev.find((a) => a.localId === localId);
                if (target) revoke(target);
                return prev.filter((a) => a.localId !== localId);
            });
        },
        [revoke]
    );

    const clearAttachments = useCallback(() => {
        setAttachments((prev) => {
            prev.forEach(revoke);
            return [];
        });
    }, [revoke]);

    const uploading = attachments.some((a) => a.status === 'uploading');
    const readyAttachments = attachments
        .filter((a) => a.status === 'ready' && a.uploaded)
        .map((a) => a.uploaded as AgentChatAttachment);

    return {
        attachments,
        addFiles,
        removeAttachment,
        clearAttachments,
        uploading,
        readyAttachments,
    };
}
