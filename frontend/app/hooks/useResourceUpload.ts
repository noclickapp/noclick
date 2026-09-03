// Hook for uploading files to R2 via the resource system.
// Encapsulates the 3-step flow: create resource → get presigned URL → PUT blob.

import { useState, useCallback } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import { uploadWithProgress } from '~/lib/uploadWithProgress';
import {
  ResourceCreateRequest,
  ResourceDownloadUrlRequest,
  ResourceUploadUrlRequest,
} from '~/types/socket-events.generated';

// Mirrors the server cap in backend/wss/handlers/resource_handler.py.
const MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024; // 100 MB

export interface UploadedResource {
  resourceId: string;
  /** Browser-resolvable URL; may be a short-lived signed URL on private storage. */
  publicUrl: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
}

export function useResourceUpload() {
  const [uploading, setUploading] = useState(false);
  // Byte fraction (0..1) of the in-flight PUT, null when idle. With parallel
  // uploads from one hook instance this is last-writer-wins — concurrent
  // callers should use the per-call onProgress instead.
  const [progress, setProgress] = useState<number | null>(null);

  const uploadFile = useCallback(
    async (
      file: File,
      workflowId: string,
      /** Producing node, or null for an upload not tied to a node (Dashboard Files). */
      nodeId: string | null,
      onProgress?: (fraction: number) => void,
    ): Promise<UploadedResource> => {
      if (file.size > MAX_UPLOAD_SIZE_BYTES) {
        throw new Error(`File too large (${(file.size / (1024 * 1024)).toFixed(1)} MB). Maximum size is ${MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)} MB.`);
      }
      setUploading(true);
      setProgress(0);
      try {
        // 1. Create resource record
        const createRes = await sendEventAsync(
          ResourceCreateRequest.create({
            workflow_id: workflowId,
            resource_type: 'file',
            name: file.name,
            node_id: nodeId,
            mime_type: file.type || 'application/octet-stream',
            size_bytes: file.size,
          })
        );
        const resourceId = createRes.resource!.id;

        // 2. Get presigned upload URL
        const uploadRes = await sendEventAsync(
          ResourceUploadUrlRequest.create({
            resource_id: resourceId,
            filename: file.name,
            content_type: file.type || 'application/octet-stream',
          })
        );

        // 3. PUT blob to object storage with byte-level progress
        const putRes = await uploadWithProgress(uploadRes.upload_url, file, {
          method: 'PUT',
          headers: { 'Content-Type': file.type || 'application/octet-stream' },
          onProgress: fraction => {
            setProgress(fraction);
            onProgress?.(fraction);
          },
        });
        if (!putRes.ok) {
          throw new Error(`Object storage upload failed: ${putRes.status} ${putRes.statusText}`);
        }

        // The storage bucket is private in the community edition, so the URL
        // handed to fields must come from the authenticated backend instead of
        // being assembled from a public bucket base. Hosted returns its CDN URL;
        // self-hosted returns a short-lived presigned GET.
        const downloadRes = await sendEventAsync(
          ResourceDownloadUrlRequest.create({ resource_id: resourceId })
        );

        return {
          resourceId,
          publicUrl: downloadRes.download_url,
          name: file.name,
          mimeType: file.type || 'application/octet-stream',
          sizeBytes: file.size,
        };
      } finally {
        setUploading(false);
        setProgress(null);
      }
    },
    []
  );

  return { uploadFile, uploading, progress };
}
