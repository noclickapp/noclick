// Renders a data table using AG Grid with dark theme.
// Supports data from execution output, CSV file upload, configured dataset
// resources, or inline config rows.

import { useContext, useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { AgGridReact } from 'ag-grid-react';
import { ModuleRegistry } from '@ag-grid-community/core';
import { ClientSideRowModelModule } from '@ag-grid-community/client-side-row-model';
import { Table, Loader2, RefreshCw } from 'lucide-react';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-quartz.css';
import type { BlockComponentProps } from '../types';
import { sendEventAsync } from '~/lib/socket-sender';
import {
  ResourceCreateRequest,
  ResourceDatasetAppendRequest,
  ResourceDatasetRowsRequest,
} from '~/types/socket-events.generated';
import { useWorkflowId } from '~/components/workflow/WorkflowContext';
import { BlockHeaderSlotContext } from '../BlockWrapper';

ModuleRegistry.registerModules([ClientSideRowModelModule]);

type Row = Record<string, unknown>;

const SAMPLE_COLUMNS = [
  { field: 'id', headerName: '#', width: 60 },
  { field: 'name', headerName: 'Name' },
  { field: 'category', headerName: 'Category' },
  { field: 'value', headerName: 'Value', width: 100 },
];

const SAMPLE_ROWS: Row[] = [
  { id: 1, name: 'Alpha', category: 'A', value: 120 },
  { id: 2, name: 'Beta', category: 'B', value: 340 },
  { id: 3, name: 'Gamma', category: 'A', value: 210 },
  { id: 4, name: 'Delta', category: 'C', value: 90 },
  { id: 5, name: 'Epsilon', category: 'B', value: 450 },
];

function parseCSV(text: string): Row[] {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
  return lines.slice(1).map(line => {
    const values = line.split(',').map(v => v.trim().replace(/^"|"$/g, ''));
    const row: Row = {};
    headers.forEach((h, i) => {
      const v = values[i] ?? '';
      const num = Number(v);
      row[h] = v !== '' && !isNaN(num) ? num : v;
    });
    return row;
  });
}

function nonEmptyArray(value: unknown): Row[] | null {
  return Array.isArray(value) && value.length > 0 ? (value as Row[]) : null;
}

export function DataframeBlock({ id, config, output, onConfigChange }: BlockComponentProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [csvData, setCsvData] = useState<Row[] | null>(null);
  const [resourceRows, setResourceRows] = useState<Row[] | null>(null);
  const [loadingResource, setLoadingResource] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const workflowId = useWorkflowId();
  const headerSlot = useContext(BlockHeaderSlotContext);

  const resourceId = (config.resource_id as string) || '';

  // Fetch rows for the selected dataset. The `signal` arg lets the auto-load
  // effect cancel its in-flight request on unmount; the manual refresh button
  // calls without one (it always wants to apply its result).
  const fetchResourceRows = useCallback(
    async (signal?: { cancelled: boolean }) => {
      if (!resourceId) return;
      setLoadingResource(true);
      try {
        const res = await sendEventAsync(
          ResourceDatasetRowsRequest.create({ resource_id: resourceId, limit: 10000 }),
        );
        if (signal?.cancelled) return;
        setResourceRows(res.rows.map(r => r.data as Row));
      } catch (err) {
        if (signal?.cancelled) return;
        console.error('[Dataframe] failed to load dataset rows:', err);
        setResourceRows(null);
      } finally {
        if (!signal?.cancelled) setLoadingResource(false);
      }
    },
    [resourceId],
  );

  // Auto-load on resource_id change. Skipped while a just-uploaded CSV is still
  // in memory so the freshly-rendered rows don't flash to a refetched copy.
  useEffect(() => {
    if (!resourceId || csvData) {
      setResourceRows(null);
      setLoadingResource(false);
      return;
    }
    const signal = { cancelled: false };
    fetchResourceRows(signal);
    return () => { signal.cancelled = true; };
  }, [resourceId, csvData, fetchResourceRows]);

  const handleCSV = useCallback(async (file: File) => {
    if (!workflowId) return;
    setUploading(true);
    try {
      const text = await file.text();
      const rows = parseCSV(text);
      if (rows.length === 0) return;

      setCsvData(rows);

      const createRes = await sendEventAsync(
        ResourceCreateRequest.create({
          workflow_id: workflowId,
          resource_type: 'dataset',
          name: file.name,
          node_id: id,
          metadata: { row_count: rows.length },
        }),
      );
      const newResourceId = createRes.resource!.id;

      await sendEventAsync(
        ResourceDatasetAppendRequest.create({ resource_id: newResourceId, rows }),
      );

      onConfigChange({ ...config, resource_id: newResourceId });
    } catch (err) {
      console.error('[Dataframe] CSV upload failed:', err);
    } finally {
      setUploading(false);
    }
  }, [workflowId, id, config, onConfigChange]);

  // First available real data source in priority order, or null if none is ready.
  const realData = useMemo<Row[] | null>(() => {
    return (
      nonEmptyArray(output?.data)
      ?? (csvData && csvData.length > 0 ? csvData : null)
      ?? (resourceRows && resourceRows.length > 0 ? resourceRows : null)
      ?? nonEmptyArray(config.rowData)
    );
  }, [output?.data, csvData, resourceRows, config.rowData]);

  const columnDefs = useMemo(() => {
    if (config.columnDefs) return config.columnDefs as typeof SAMPLE_COLUMNS;
    if (!realData) return SAMPLE_COLUMNS;
    return Object.keys(realData[0]).map(field => ({
      field,
      headerName: field.charAt(0).toUpperCase() + field.slice(1),
    }));
  }, [realData, config.columnDefs]);

  // Upload zone shows only when nothing is wired up at all. Once a dataset is
  // selected we trust the fetch is in flight (loading overlay handles that).
  if (!realData && !resourceId && !loadingResource) {
    return (
      <div
        className={`w-full h-full flex items-center justify-center rounded-md border-2 border-dashed transition-colors cursor-pointer ${
          isDragOver ? 'border-blue-500 bg-blue-500/10' : 'border-border dark:border-zinc-700 bg-muted/50 hover:border-border dark:hover:border-zinc-600'
        }`}
        onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={e => {
          e.preventDefault();
          setIsDragOver(false);
          const file = e.dataTransfer.files[0];
          if (file?.name.endsWith('.csv')) handleCSV(file);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <div className="flex flex-col items-center gap-2 text-muted-foreground/70 dark:text-zinc-600">
          {uploading ? <Loader2 className="w-8 h-8 animate-spin text-blue-600 dark:text-blue-400" /> : <Table className="w-8 h-8" />}
          <span className="text-xs">{uploading ? 'Processing CSV...' : 'Drop CSV or click to browse'}</span>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          className="hidden"
          onChange={e => {
            const file = e.target.files?.[0];
            if (file) handleCSV(file);
            e.target.value = '';
          }}
        />
      </div>
    );
  }

  // Refresh button lives in the BlockWrapper title bar via portal. Only meaningful
  // for the persisted dataset path — output comes from upstream execution, csvData
  // is local-only, and config.rowData is inline. Hidden in those cases.
  const showRefresh = !!resourceId && !csvData;

  return (
    <div
      className="w-full h-full ag-theme-quartz-dark relative"
      style={{
        '--ag-background-color': '#232328',
        '--ag-header-background-color': '#34343a',
        '--ag-active-color': '#a1a1aa',
      } as React.CSSProperties}
    >
      {showRefresh && headerSlot && createPortal(
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); fetchResourceRows(); }}
          disabled={loadingResource}
          title="Refresh dataset"
          className="p-1.5 rounded-full text-muted-foreground hover:text-foreground hover:bg-foreground/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loadingResource ? 'animate-spin' : ''}`} />
        </button>,
        headerSlot,
      )}
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      <AgGridReact
        columnDefs={columnDefs as any}
        rowData={realData ?? SAMPLE_ROWS}
        headerHeight={28}
        rowHeight={28}
        suppressCellFocus
        domLayout="normal"
      />
      {loadingResource && !realData && (
        <div className="absolute inset-0 flex items-center justify-center bg-card/60 rounded-md pointer-events-none">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      )}
    </div>
  );
}
