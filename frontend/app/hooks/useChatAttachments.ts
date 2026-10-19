// Attachment-tray state for chat composers: accepts files from the picker,
// paste, or drag-drop, uploads each at once through the caller's uploader, and
// exposes the ready set for the send payload. `addReady` takes a file that is
// already uploaded (one picked from your files). An agent node's chat uploads
// to the workflow's resources (useChatAttachments); the coordinator's to the
// account's own files (useAttachmentTray with its uploader).

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import { isImageAttachment, type AgentChatAttachment } from '~/lib/agentChat';

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

/** Uploads one file, reporting byte progress, and resolves to what the send payload carries. */
export type ChatUpload = (file: File, onProgress: (fraction: number) => void) => Promise<AgentChatAttachment>;

let nextLocalId = 0;

export function useAttachmentTray(upload: ChatUpload | null) {
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
            if (!upload) return;
            for (const file of Array.from(files)) {
                const localId = `chat-att-${nextLocalId++}`;
                const name = file.name || 'pasted-image.png';
                const previewUrl = file.type.startsWith('image/')
                    ? URL.createObjectURL(file)
                    : undefined;
                if (previewUrl) previewUrlsRef.current.add(previewUrl);
                setAttachments((prev) =>
                    prev.concat({
                        localId,
                        name,
                        mimeType: file.type || 'application/octet-stream',
                        sizeBytes: file.size,
                        previewUrl,
                        status: 'uploading',
                        progress: 0,
                    })
                );
                upload(file, (fraction) =>
                    setAttachments((prev) =>
                        prev.map((a) =>
                            a.localId === localId && a.status === 'uploading'
                                ? { ...a, progress: fraction }
                                : a
                        )
                    )
                ).then(
                    (uploaded) =>
                        setAttachments((prev) =>
                            prev.map((a) =>
                                a.localId === localId
                                    ? { ...a, status: 'ready', uploaded: { ...uploaded, name } }
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
        [upload]
    );

    /** A file that's already uploaded, straight into the tray as ready (once). */
    const addReady = useCallback((attachment: AgentChatAttachment) => {
        setAttachments((prev) =>
            prev.some((a) => a.uploaded?.resourceId === attachment.resourceId)
                ? prev
                : prev.concat({
                      localId: `chat-att-${nextLocalId++}`,
                      name: attachment.name,
                      mimeType: attachment.mimeType,
                      sizeBytes: attachment.sizeBytes,
                      previewUrl: isImageAttachment(attachment) ? attachment.url : undefined,
                      status: 'ready',
                      uploaded: attachment,
                  })
        );
    }, []);

    const revoke = useCallback((a: PendingChatAttachment) => {
        if (a.previewUrl && previewUrlsRef.current.has(a.previewUrl)) {
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
        addReady,
        removeAttachment,
        clearAttachments,
        uploading,
        readyAttachments,
    };
}

/** An agent node's chat: files upload as the workflow's resources, produced by the node. */
export function useChatAttachments(workflowId: string | undefined, nodeId: string) {
    const { uploadFile } = useResourceUpload();
    const upload = useMemo<ChatUpload | null>(
        () =>
            workflowId
                ? async (file, onProgress) => {
                      const res = await uploadFile(file, workflowId, nodeId, onProgress);
                      return { resourceId: res.resourceId, url: res.publicUrl, name: res.name, mimeType: res.mimeType, sizeBytes: res.sizeBytes };
                  }
                : null,
        [workflowId, nodeId, uploadFile]
    );
    return useAttachmentTray(upload);
}
