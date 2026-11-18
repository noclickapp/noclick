// Blob/file resource management via R2 storage.

import { request } from './transport.js';

export interface ResourceInfo {
  id: string;
  name: string;
  resourceType: string;
  mimeType: string | null;
  sizeBytes: number | null;
}

export interface UploadResult {
  resourceId: string;
  uploadUrl: string;
}

/**
 * Create a resource and get a presigned upload URL.
 * After calling this, PUT the file body to the uploadUrl.
 */
export function upload(
  name: string,
  mimeType: string,
  sizeBytes: number,
  resourceType: string = 'file'
): Promise<UploadResult> {
  return request('resources.upload', { name, mimeType, sizeBytes, resourceType });
}

/** Get a presigned download URL for a resource. */
export function getUrl(resourceId: string): Promise<string> {
  return request('resources.getUrl', { resourceId });
}

/** Delete a resource. */
export function remove(resourceId: string): Promise<void> {
  return request('resources.remove', { resourceId });
}

/** List resources in the workflow. */
export function list(resourceType?: string): Promise<ResourceInfo[]> {
  return request('resources.list', { ...(resourceType ? { resourceType } : {}) });
}
