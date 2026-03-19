// Tabular dataset operations (CRUD on dataset_rows).

import { request } from './transport.js';

export interface DatasetRow {
  id: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DatasetPage {
  rows: DatasetRow[];
  totalCount: number;
}

export interface DatasetInfo {
  id: string;
  name: string;
  rowCount: number;
}

/** List all datasets in the workflow. */
export function list(): Promise<DatasetInfo[]> {
  return request('dataset.list');
}

/**
 * Create a new dataset resource.
 * @param name - Display name for the dataset
 * @returns The resource ID of the created dataset
 */
export function create(name: string): Promise<string> {
  return request('dataset.create', { name });
}

/**
 * Get paginated rows from a dataset resource.
 * @param resourceId - UUID of the dataset resource
 */
export function getRows(
  resourceId: string,
  options?: { limit?: number; offset?: number }
): Promise<DatasetPage> {
  return request('dataset.getRows', { resourceId, ...options });
}

/**
 * Append rows to a dataset.
 * @param resourceId - UUID of the dataset resource
 * @param rows - Array of row data objects
 */
export function appendRows(
  resourceId: string,
  rows: Record<string, unknown>[]
): Promise<{ insertedCount: number }> {
  return request('dataset.appendRows', { resourceId, rows });
}

/**
 * Update a single row in a dataset.
 * @param resourceId - UUID of the dataset resource
 * @param rowId - UUID of the row to update
 * @param data - New data for the row
 */
export function updateRow(
  resourceId: string,
  rowId: string,
  data: Record<string, unknown>
): Promise<void> {
  return request('dataset.updateRow', { resourceId, rowId, data });
}

/**
 * Delete rows from a dataset.
 * @param resourceId - UUID of the dataset resource
 * @param rowIds - UUIDs of rows to delete
 */
export function deleteRows(
  resourceId: string,
  rowIds: string[]
): Promise<{ deletedCount: number }> {
  return request('dataset.deleteRows', { resourceId, rowIds });
}
