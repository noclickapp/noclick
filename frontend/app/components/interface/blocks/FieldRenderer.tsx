// Shared form field renderer used by FormBlock (and the approval/setup forms).
// Renders native HTML inputs for each field type (text, number, checkbox, dropdown, credential, etc.).

import { useMemo, useState, useRef, useCallback } from 'react';
import { CheckCircle2, Upload, FileText, X, Loader2, AlertCircle } from 'lucide-react';
import { StringListInput } from '~/components/shared/StringListInput';
import type { FormField, FormFieldType } from '../types';
import { SchedulesWidget } from '~/components/workflow/SchedulesWidget';
import { GenerationCredentialSelector } from '~/components/workflow/GenerationCredentialSelector';
import { WhatsAppQRCredentialForm } from '~/components/workflow/WhatsAppQRCredentialForm';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { getServiceForCredentialType } from '~/utils/credentialTypes';
import { useCredentialVariablesContext } from '~/contexts/CredentialVariablesContext';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import { useRenewableResourceUrl } from '~/hooks/useRenewableResourceUrl';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { useWorkflowId } from '~/components/workflow/WorkflowContext';

/**
 * Returns true when the given credentialType corresponds to a QR-scan credential
 * (i.e. its schema def has x-credential-type === "qr_scan").
 * Matches via the `credential_type.const` property inside the schema def so the
 * check is reliable regardless of class naming conventions.
 */
function isQRScanCredentialType(credType: string, nodeType: string | undefined): boolean {
  if (!credType || !nodeType) return false;
  const schema = (NODE_SCHEMAS as any)[nodeType];
  if (!schema) return false;
  const defs: Record<string, any> = schema.$defs || schema.definitions || {};
  return Object.values(defs).some(
    (def: any) =>
      def?.['x-credential-type'] === 'qr_scan' &&
      def?.properties?.credential_type?.const === credType,
  );
}

/** Map backend field types (from FormFieldsEditor/Pydantic) to frontend FormField types */
export const BACKEND_TYPE_MAP: Record<string, FormFieldType> = {
  string: 'text',
  number: 'number',
  boolean: 'checkbox',
  select: 'dropdown',
  schedule: 'schedule',
  list: 'list',
  array: 'list',
  file: 'file',
  credential: 'credential',
};

/** True if a File satisfies an HTML `accept` string ("image/*", ".pdf", "audio/*,video/*"). Empty = any. */
function matchesAccept(file: File, accept?: string): boolean {
  if (!accept) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return accept.split(',').map(t => t.trim().toLowerCase()).filter(Boolean).some(token => {
    if (token.startsWith('.')) return name.endsWith(token);
    if (token.endsWith('/*')) return type.startsWith(token.slice(0, -1));
    return type === token;
  });
}

/** Normalize fields from backend format ({name, type:"string"}) to frontend format ({id, type:"text"}) */
export function normalizeFields(raw: unknown[]): FormField[] {
  return raw.map((f: any) => ({
    ...f,
    id: f.id ?? f.name ?? 'field',
    type: BACKEND_TYPE_MAP[f.type] ?? f.type ?? 'text',
    label: f.label || f.name || 'Field',
    placeholder: f.placeholder ?? f.description ?? '',
    // Backend FormField declares `default`; the frontend field shape calls it defaultValue
    defaultValue: f.defaultValue ?? f.default,
    // Derive credential fields from service registry
    credentialType: f.credential_type ?? f.credentialType,
    acceptedCredentialTypes: (() => {
      const ct = f.credential_type ?? f.credentialType;
      if (!ct) return undefined;
      return getServiceForCredentialType(ct)?.acceptedCredentialTypes ?? [ct];
    })(),
  }));
}

const BASE_INPUT_CLASS =
  'w-full px-2.5 py-2.5 text-xs bg-card border border-border dark:border-zinc-700 rounded-md text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-blue-500/50 transition-colors';

export function FieldRenderer({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: string | number | boolean | unknown;
  onChange: (id: string, value: string | number | boolean | unknown) => void;
}) {
  return (
    <div className="space-y-1">
      <label className="text-[11px] font-medium text-muted-foreground block">
        {field.label}
        {field.required && <span className="text-red-600 dark:text-red-400 ml-0.5">*</span>}
      </label>

      {field.type === 'text' && (
        <input
          type="text"
          className={BASE_INPUT_CLASS}
          placeholder={field.placeholder}
          value={(value as string) ?? (field.defaultValue as string) ?? ''}
          onChange={e => onChange(field.id, e.target.value)}
        />
      )}

      {field.type === 'textarea' && (
        <textarea
          className={`${BASE_INPUT_CLASS} resize-none`}
          rows={3}
          placeholder={field.placeholder}
          value={(value as string) ?? (field.defaultValue as string) ?? ''}
          onChange={e => onChange(field.id, e.target.value)}
        />
      )}

      {field.type === 'number' && (
        <input
          type="number"
          className={BASE_INPUT_CLASS}
          placeholder={field.placeholder}
          min={field.min}
          max={field.max}
          step={field.step}
          value={(value as number) ?? (field.defaultValue as number) ?? ''}
          onChange={e => onChange(field.id, e.target.valueAsNumber)}
        />
      )}

      {field.type === 'checkbox' && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="w-3.5 h-3.5 rounded border-border dark:border-zinc-600 bg-card text-blue-500 focus:ring-0 focus:ring-offset-0"
            checked={(value as boolean) ?? (field.defaultValue as boolean) ?? false}
            onChange={e => onChange(field.id, e.target.checked)}
          />
          <span className="text-[11px] text-muted-foreground">{field.placeholder || field.label}</span>
        </label>
      )}

      {field.type === 'dropdown' && (
        <select
          className={BASE_INPUT_CLASS}
          value={(value as string) ?? (field.defaultValue as string) ?? ''}
          onChange={e => onChange(field.id, e.target.value)}
        >
          <option value="" className="bg-card">
            {field.placeholder || 'Select...'}
          </option>
          {field.options?.map(opt => {
            const optValue = typeof opt === 'string' ? opt : opt.value;
            const optLabel = typeof opt === 'string' ? opt : opt.label;
            return (
              <option key={optValue} value={optValue} className="bg-card">
                {optLabel}
              </option>
            );
          })}
        </select>
      )}

      {field.type === 'slider' && (
        <div className="flex items-center gap-2">
          <input
            type="range"
            className="flex-1 accent-blue-500 h-1.5"
            min={field.min ?? 0}
            max={field.max ?? 100}
            step={field.step ?? 1}
            value={(value as number) ?? (field.defaultValue as number) ?? 50}
            onChange={e => onChange(field.id, e.target.valueAsNumber)}
          />
          <span className="text-[10px] text-muted-foreground dark:text-zinc-500 tabular-nums w-6 text-right">
            {(value as number) ?? (field.defaultValue as number) ?? 50}
          </span>
        </div>
      )}

      {field.type === 'radio' && (
        <div className="space-y-1">
          {field.options?.map(opt => {
            const optValue = typeof opt === 'string' ? opt : opt.value;
            const optLabel = typeof opt === 'string' ? opt : opt.label;
            return (
              <label key={optValue} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name={field.id}
                  className="w-3 h-3 border-border dark:border-zinc-600 bg-card text-blue-500 focus:ring-0 focus:ring-offset-0"
                  checked={(value as string) === optValue}
                  onChange={() => onChange(field.id, optValue)}
                />
                <span className="text-[11px] text-muted-foreground">{optLabel}</span>
              </label>
            );
          })}
        </div>
      )}

      {field.type === 'date' && (
        <input
          type="date"
          className={BASE_INPUT_CLASS}
          value={(value as string) ?? (field.defaultValue as string) ?? ''}
          onChange={e => onChange(field.id, e.target.value)}
        />
      )}

      {field.type === 'color' && (
        <div className="flex items-center gap-2">
          <input
            type="color"
            className="w-8 h-8 rounded border border-border dark:border-zinc-700 bg-card cursor-pointer"
            value={(value as string) ?? (field.defaultValue as string) ?? '#3b82f6'}
            onChange={e => onChange(field.id, e.target.value)}
          />
          <span className="text-[10px] text-muted-foreground dark:text-zinc-500 font-mono">
            {(value as string) ?? (field.defaultValue as string) ?? '#3b82f6'}
          </span>
        </div>
      )}

      {field.type === 'list' && (
        <ListField
          items={Array.isArray(value) ? (value as string[]) : []}
          placeholder={field.placeholder}
          onChange={(items) => onChange(field.id, items)}
        />
      )}

      {field.type === 'schedule' && (
        <SchedulesWidget
          value={(value as any) ?? [{ frequency: 'day', hour: 9, minute: 0, dayOfWeek: 1, dayOfMonth: 1 }]}
          onChange={(newValue) => onChange(field.id, newValue)}
          fieldKey={`config-form-${field.id}`}
        />
      )}

      {field.type === 'file' && (
        <FormFileField field={field} value={value} onChange={onChange} />
      )}

      {field.type === 'credential' && (
        <CredentialFieldRenderer
          field={field}
          value={(value as string) ?? ''}
          onChange={onChange}
        />
      )}
    </div>
  );
}

/** File upload field — accepts any file (or an `accept`-filtered subset), uploads
 *  to the workflow-resource store, and persists its durable resource ID. The
 *  browser resolves a fresh private download URL when rendering the field. */
function FormFileField({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: string | number | boolean | unknown;
  onChange: (id: string, value: string | number | boolean | unknown) => void;
}) {
  const { uploadFile, uploading, progress } = useResourceUpload();
  const workflowId = useWorkflowId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const storedValue = typeof value === 'string' ? value : '';
  const {
    url,
    isResourceId,
    resolving,
    error: resolveError,
  } = useRenewableResourceUrl(storedValue);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      if (!workflowId) { setError('File upload is unavailable here.'); return; }
      if (!matchesAccept(file, field.accept)) {
        setError(`This field only accepts ${field.accept} files.`);
        return;
      }
      try {
        const res = await uploadFile(file, workflowId, `form-${field.id}`);
        setFileName(file.name);
        onChange(field.id, res.resourceId);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed.');
      }
    },
    [workflowId, field.id, field.accept, uploadFile, onChange],
  );

  if (storedValue) {
    return (
      <div className="flex items-center gap-2 px-2.5 py-2 rounded-md border border-border dark:border-zinc-700 bg-card">
        <FileText className="w-3.5 h-3.5 flex-shrink-0 text-emerald-600 dark:text-emerald-400" />
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer"
            className="text-[11px] text-foreground truncate min-w-0 hover:underline">
            {fileName || (isResourceId ? 'Uploaded file' : url.split('/').pop()) || 'Uploaded file'}
          </a>
        ) : (
          <span className={`text-[11px] truncate min-w-0 ${resolveError ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
            {resolveError || (resolving ? 'Preparing download…' : 'Uploaded file')}
          </span>
        )}
        <button type="button" onClick={() => { setFileName(null); onChange(field.id, ''); }}
          className="ml-auto flex-shrink-0 p-0.5 rounded text-muted-foreground hover:text-foreground">
          <X className="w-3 h-3" />
        </button>
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className={`w-full flex items-center gap-2 px-2.5 py-2.5 rounded-md border border-dashed text-[11px] transition-colors ${
          error ? 'border-red-500 text-red-600 dark:text-red-400 bg-red-500/5'
            : 'border-border dark:border-zinc-700 text-muted-foreground hover:border-blue-500/50'
        }`}
      >
        {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600 dark:text-blue-400" />
          : error ? <AlertCircle className="w-3.5 h-3.5" />
          : <Upload className="w-3.5 h-3.5" />}
        <span className="truncate tabular-nums">
          {uploading ? `Uploading… ${Math.round((progress ?? 0) * 100)}%`
            : error ? error : (field.placeholder || 'Click to upload a file')}
        </span>
        {uploading && <UploadProgressBar fraction={progress ?? 0} className="flex-1 min-w-[48px] h-0.5" />}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={field.accept || undefined}
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }}
      />
    </>
  );
}

/** Credential selector field — renders QR scan UI or GenerationCredentialSelector depending on credential type. */
function CredentialFieldRenderer({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: string;
  onChange: (id: string, value: string | number | boolean | unknown) => void;
}) {
  const credType = field.credentialType || '';
  const acceptedTypes = useMemo(
    () => field.acceptedCredentialTypes || (credType ? [credType] : []),
    [field.acceptedCredentialTypes, credType],
  );
  // Derive node type so GenerationCredentialSelector can load non-OAuth credential schemas
  const serviceNodeType = useMemo(() => getServiceForCredentialType(credType)?.value, [credType]);
  // Credential variables from set-variable nodes in the workflow (provided via context from FlowCanvas)
  const credentialVariables = useCredentialVariablesContext();

  // QR scan credentials (e.g. whatsapp_qr) need the dedicated QR flow, not a standard form
  const isQRScan = useMemo(
    () => isQRScanCredentialType(credType, serviceNodeType),
    [credType, serviceNodeType],
  );

  // Build the input request for GenerationCredentialSelector (always computed, conditionally used)
  const input: InputRequest = useMemo(
    () => ({
      id: `form-cred-${field.id}`,
      nodeId: '',
      type: 'credential',
      label: field.label || 'Connect credential',
      description: field.placeholder || 'Select or connect a credential',
      credentialType: credType,
      acceptedCredentialTypes: acceptedTypes,
      required: field.required ?? false,
      value: value || undefined,
    }),
    [field.id, field.label, field.placeholder, field.required, credType, acceptedTypes, value],
  );

  // QR scan credentials (e.g. whatsapp_qr) bypass the standard selector and show the scan flow
  if (isQRScan) {
    if (value) {
      // Already connected — show success badge with option to reconnect
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
            <span className="text-sm text-emerald-700 dark:text-emerald-300">WhatsApp connected</span>
          </div>
          <button
            type="button"
            onClick={() => onChange(field.id, '')}
            className="text-[11px] text-muted-foreground dark:text-zinc-500 hover:text-muted-foreground transition-colors"
          >
            Connect a different account
          </button>
        </div>
      );
    }
    return (
      <WhatsAppQRCredentialForm
        credentialType={credType}
        onCredentialCreated={(credentialId) => onChange(field.id, credentialId)}
      />
    );
  }

  return (
    <GenerationCredentialSelector
      input={input}
      onCredentialSelect={(credentialId) => onChange(field.id, credentialId)}
      selectedCredentialId={value || undefined}
      nodeType={serviceNodeType}
      credentialVariables={credentialVariables.length > 0 ? credentialVariables : undefined}
    />
  );
}

/** Multi-value string list input. Delegates to the shared StringListInput so
 * the entry UX (auto-append + autosave, no Enter required) matches the node
 * config "list" widget. */
function ListField({
  items,
  placeholder,
  onChange,
}: {
  items: string[];
  placeholder?: string;
  onChange: (items: string[]) => void;
}) {
  return (
    <StringListInput
      value={items}
      onChange={onChange}
      placeholder={placeholder}
      inputClassName="flex-1 px-2.5 py-1.5 text-xs bg-card border border-border dark:border-zinc-700 rounded-md text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-blue-500/50 transition-colors"
      trailingClassName="!border-border/60 dark:border-zinc-700/60 !border-dashed"
    />
  );
}
