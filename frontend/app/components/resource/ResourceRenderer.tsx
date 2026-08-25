// Reusable resource renderer that dispatches to the correct preview component
// based on a resource's mime_type. Used by the Resources tab and anywhere else
// that needs to display resource content (images, video, audio, markdown, CSV, etc.).

import { useEffect, useState } from 'react';
import {
  Image, Volume2, Video, FileText, Database, File, Loader2,
  Table2, Braces, Code, Terminal, FileCode2, FileType,
} from 'lucide-react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import type { ResourceInfo } from '~/types/socket-events.generated';

// -- Type resolution ----------------------------------------------------------

/** Resolve the effective media type from mime_type, since resource_type may be 'file' for all uploads. */
export function resolveMediaType(resource: ResourceInfo): string {
  const mime = resource.mime_type || '';
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('audio/')) return 'audio';
  if (mime.includes('pdf')) return 'document';
  if (resource.resource_type === 'dataset') return 'dataset';
  return resource.resource_type || 'file';
}

export const RESOURCE_TYPE_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  color: string;
  bg: string;
}> = {
  image:    { icon: Image,    label: 'Image',    color: 'text-blue-600 dark:text-blue-400',       bg: 'bg-blue-500/10' },
  audio:    { icon: Volume2,  label: 'Audio',    color: 'text-purple-600 dark:text-purple-400',   bg: 'bg-purple-500/10' },
  video:    { icon: Video,    label: 'Video',    color: 'text-pink-600 dark:text-pink-400',       bg: 'bg-pink-500/10' },
  document: { icon: FileText, label: 'Document', color: 'text-orange-600 dark:text-orange-400',   bg: 'bg-orange-500/10' },
  dataset:  { icon: Database, label: 'Dataset',  color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10' },
  file:     { icon: File,     label: 'File',     color: 'text-muted-foreground',                  bg: 'bg-zinc-500/10' },
};

export function getTypeConfig(type: string) {
  return RESOURCE_TYPE_CONFIG[type] || RESOURCE_TYPE_CONFIG.file;
}

// -- File extension thumbnail config ------------------------------------------

type ThumbnailConfig = { icon: React.ComponentType<{ className?: string }>; label: string; color: string; bg: string };

const FILE_EXT_CONFIG: Record<string, ThumbnailConfig> = {
  pdf:  { icon: FileText,  label: 'PDF',        color: 'text-red-600 dark:text-red-400',         bg: 'bg-red-500/10' },
  csv:  { icon: Table2,    label: 'CSV',        color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/10' },
  md:   { icon: FileType,  label: 'Markdown',   color: 'text-sky-600 dark:text-sky-400',         bg: 'bg-sky-500/10' },
  json: { icon: Braces,    label: 'JSON',       color: 'text-amber-600 dark:text-amber-400',     bg: 'bg-amber-500/10' },
  xml:  { icon: FileCode2, label: 'XML',        color: 'text-orange-600 dark:text-orange-400',   bg: 'bg-orange-500/10' },
  yaml: { icon: FileCode2, label: 'YAML',       color: 'text-orange-600 dark:text-orange-300',   bg: 'bg-orange-500/10' },
  yml:  { icon: FileCode2, label: 'YAML',       color: 'text-orange-600 dark:text-orange-300',   bg: 'bg-orange-500/10' },
  py:   { icon: Code,      label: 'Python',     color: 'text-yellow-600 dark:text-yellow-400',   bg: 'bg-yellow-500/10' },
  js:   { icon: Code,      label: 'JavaScript', color: 'text-yellow-600 dark:text-yellow-300',   bg: 'bg-yellow-500/10' },
  ts:   { icon: Code,      label: 'TypeScript', color: 'text-blue-600 dark:text-blue-400',       bg: 'bg-blue-500/10' },
  html: { icon: Code,      label: 'HTML',       color: 'text-orange-600 dark:text-orange-400',   bg: 'bg-orange-500/10' },
  css:  { icon: Code,      label: 'CSS',        color: 'text-indigo-600 dark:text-indigo-400',   bg: 'bg-indigo-500/10' },
  sh:   { icon: Terminal,   label: 'Shell',      color: 'text-green-600 dark:text-green-400',     bg: 'bg-green-500/10' },
  txt:  { icon: FileText,  label: 'Text',       color: 'text-muted-foreground',                  bg: 'bg-zinc-500/10' },
  log:  { icon: FileText,  label: 'Log',        color: 'text-muted-foreground/70 dark:text-zinc-500',               bg: 'bg-zinc-500/10' },
};

/** Get a thumbnail config tuned to the file's extension, falling back to media-type config. */
export function getThumbnailConfig(resource: ResourceInfo): ThumbnailConfig {
  const mediaType = resolveMediaType(resource);
  // For media types with real previews (image/video/audio), use the broad config
  if (['image', 'video', 'audio', 'dataset'].includes(mediaType)) {
    return getTypeConfig(mediaType);
  }
  // Check file extension for specific styling
  const ext = resource.name.split('.').pop()?.toLowerCase() || '';
  if (FILE_EXT_CONFIG[ext]) return FILE_EXT_CONFIG[ext];
  // Fall back to media-type config
  return getTypeConfig(mediaType);
}

// -- Format helpers -----------------------------------------------------------

export function formatSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return `Today, ${d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })}`;
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

// -- Content detection --------------------------------------------------------

const TEXT_EXTENSIONS = ['.txt', '.md', '.csv', '.json', '.xml', '.yaml', '.yml', '.log', '.html', '.css', '.js', '.ts', '.py', '.sh'];

export function isTextViewable(resource: ResourceInfo): boolean {
  const mime = resource.mime_type || '';
  if (mime.startsWith('text/') || mime === 'application/json' || mime === 'application/xml') return true;
  const name = resource.name.toLowerCase();
  return TEXT_EXTENSIONS.some(ext => name.endsWith(ext));
}

function isMarkdown(resource: ResourceInfo): boolean {
  return resource.name.toLowerCase().endsWith('.md') || resource.mime_type === 'text/markdown';
}

function isCsv(resource: ResourceInfo): boolean {
  return resource.name.toLowerCase().endsWith('.csv') || resource.mime_type === 'text/csv';
}

// -- Shared fetch hook --------------------------------------------------------

function useFetchText(url: string) {
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then(res => { if (!res.ok) throw new Error(`${res.status}`); return res.text(); })
      .then(content => { if (!cancelled) setText(content); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [url]);

  return { text, failed };
}

function FetchLoading() {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground/70 dark:text-zinc-500" />
    </div>
  );
}

function IframeFallback({ url, title }: { url: string; title: string }) {
  return <iframe src={url} title={title} className="w-full h-[75vh] bg-white rounded" />;
}

// -- Individual renderers -----------------------------------------------------

function ImageRenderer({ url, name }: { url: string; name: string }) {
  return <img src={url} alt={name} className="max-w-full max-h-[75vh] object-contain" />;
}

function VideoRenderer({ url }: { url: string }) {
  return <video src={url} controls autoPlay className="max-w-full max-h-[75vh]" />;
}

function AudioRenderer({ url }: { url: string }) {
  return (
    <div className="w-full px-8 py-10">
      <audio src={url} controls autoPlay className="w-full" />
    </div>
  );
}

function PdfRenderer({ url, name }: { url: string; name: string }) {
  return <iframe src={url} title={name} className="w-full h-[75vh]" />;
}

function TextRenderer({ url }: { url: string }) {
  const { text, failed } = useFetchText(url);
  if (failed) return <IframeFallback url={url} title="Text preview" />;
  if (text === null) return <FetchLoading />;
  return (
    <pre className="w-full max-h-[75vh] overflow-auto p-5 text-sm text-muted-foreground dark:text-zinc-300 font-mono whitespace-pre-wrap break-words leading-relaxed"
      style={{ scrollbarWidth: 'thin', scrollbarColor: 'hsl(var(--foreground) / 0.08) transparent' }}
    >
      {text}
    </pre>
  );
}

function MarkdownRendererPreview({ url }: { url: string }) {
  const { text, failed } = useFetchText(url);
  if (failed) return <IframeFallback url={url} title="Markdown preview" />;
  if (text === null) return <FetchLoading />;
  return (
    <div className="w-full max-h-[75vh] overflow-auto p-5"
      style={{ scrollbarWidth: 'thin', scrollbarColor: 'hsl(var(--foreground) / 0.08) transparent' }}
    >
      <MarkdownRenderer content={text} />
    </div>
  );
}

function parseCSV(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  if (lines.length < 1) return { headers: [], rows: [] };
  const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
  const rows = lines.slice(1).map(line =>
    line.split(',').map(v => v.trim().replace(/^"|"$/g, ''))
  );
  return { headers, rows };
}

function CsvRenderer({ url }: { url: string }) {
  const { text, failed } = useFetchText(url);
  if (failed) return <IframeFallback url={url} title="CSV preview" />;
  if (text === null) return <FetchLoading />;

  const { headers, rows } = parseCSV(text);
  if (headers.length === 0) {
    return <pre className="w-full p-5 text-sm text-muted-foreground dark:text-zinc-300 font-mono">{text}</pre>;
  }

  return (
    <div className="w-full max-h-[75vh] overflow-auto"
      style={{ scrollbarWidth: 'thin', scrollbarColor: 'hsl(var(--foreground) / 0.08) transparent' }}
    >
      <table className="w-full text-sm border-collapse">
        <thead className="sticky top-0 bg-secondary/95 backdrop-blur-sm">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground dark:text-zinc-300 border-b border-border dark:border-zinc-700">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="hover:bg-foreground/[0.03] transition-colors">
              {headers.map((_, ci) => (
                <td key={ci} className="px-3 py-1.5 text-muted-foreground border-b border-border/50 dark:border-zinc-800/50 whitespace-nowrap">
                  {row[ci] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DatasetRenderer({ resource }: { resource: ResourceInfo }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-muted-foreground dark:text-zinc-300">
      <Database className="h-10 w-10 text-emerald-600 dark:text-emerald-400" />
      <p className="text-sm">
        {(resource.metadata as Record<string, unknown>)?.row_count != null
          ? `${(resource.metadata as Record<string, unknown>).row_count} rows`
          : 'Dataset'}
      </p>
      <p className="text-xs text-muted-foreground/70 dark:text-zinc-500">{formatDate(resource.created_at)}</p>
    </div>
  );
}

function GenericFileRenderer({ resource }: { resource: ResourceInfo }) {
  return (
    <div className="flex flex-col items-center gap-4 py-10">
      <File className="h-10 w-10 text-muted-foreground/70 dark:text-zinc-500" />
      <div className="text-center">
        <p className="text-sm text-foreground/80">{resource.name}</p>
        <p className="text-xs text-muted-foreground/70 dark:text-zinc-500 mt-1">{resource.mime_type || 'Unknown type'}</p>
      </div>
    </div>
  );
}

// -- Main dispatcher ----------------------------------------------------------

export interface ResourceRendererProps {
  resource: ResourceInfo;
  url?: string;
}

/** Renders the appropriate preview for a resource based on its mime_type. */
export function ResourceRenderer({ resource, url }: ResourceRendererProps) {
  const mediaType = resolveMediaType(resource);

  if (!url && mediaType !== 'dataset') {
    return (
      <div className="flex flex-col items-center gap-2 py-12 text-muted-foreground/70 dark:text-zinc-500">
        <Loader2 className="h-6 w-6 animate-spin" />
        <span className="text-xs">Loading preview...</span>
      </div>
    );
  }

  if (mediaType === 'image' && url) return <ImageRenderer url={url} name={resource.name} />;
  if (mediaType === 'video' && url) return <VideoRenderer url={url} />;
  if (mediaType === 'audio' && url) return <AudioRenderer url={url} />;
  if (mediaType === 'document' && url) return <PdfRenderer url={url} name={resource.name} />;
  if (mediaType === 'dataset') return <DatasetRenderer resource={resource} />;

  if (url && isMarkdown(resource)) return <MarkdownRendererPreview url={url} />;
  if (url && isCsv(resource)) return <CsvRenderer url={url} />;
  if (url && isTextViewable(resource)) return <TextRenderer url={url} />;
  if (url) return <GenericFileRenderer resource={resource} />;

  return null;
}

/** Returns true if the resource preview should use a wide dialog. */
export function isWidePreview(resource: ResourceInfo): boolean {
  const mediaType = resolveMediaType(resource);
  return ['image', 'video', 'audio', 'document'].includes(mediaType) || isTextViewable(resource);
}
