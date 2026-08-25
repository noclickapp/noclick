// Universal file / attachment block. Uploads ANY file and renders the right
// viewer based on the detected type: image, audio (waveform), video, PDF
// (embed), or a generic download card. Replaces the old separate image/audio/
// video blocks — the backend detects the type; the frontend renders it.

import { useRef, useEffect, useState } from 'react';
import { Upload, X, Loader2, AlertCircle, Play, Pause, File as FileIcon, Download } from 'lucide-react';
import type { BlockComponentProps } from '../types';
import { useMediaResource } from '~/hooks/useMediaResource';
import { UploadProgressBar } from '~/components/ui/upload-progress';

type MediaKind = 'image' | 'audio' | 'video' | 'pdf' | 'file';

const EXT_KIND: Record<string, MediaKind> = {
  png: 'image', jpg: 'image', jpeg: 'image', gif: 'image', webp: 'image', svg: 'image', bmp: 'image', avif: 'image',
  mp3: 'audio', wav: 'audio', ogg: 'audio', m4a: 'audio', aac: 'audio', flac: 'audio', opus: 'audio',
  mp4: 'video', webm: 'video', mov: 'video', mkv: 'video', avi: 'video',
  pdf: 'pdf',
};

/** Detect the media kind from MIME (preferred) then filename/URL extension. */
function detectKind(url: string, mime?: string, name?: string): MediaKind {
  const m = (mime || '').toLowerCase();
  if (m.startsWith('image/')) return 'image';
  if (m.startsWith('audio/')) return 'audio';
  if (m.startsWith('video/')) return 'video';
  if (m.includes('pdf')) return 'pdf';
  const path = (name || url).toLowerCase().split('?')[0].split('#')[0];
  const ext = path.slice(path.lastIndexOf('.') + 1);
  return EXT_KIND[ext] ?? 'file';
}

export function FileBlock({ id, config, output, onConfigChange }: BlockComponentProps) {
  const out = output as Record<string, unknown> | undefined;
  // Execution output wins; the backend sets both url + src to the resolved URL.
  const executionUrl = (out?.url as string) || (out?.src as string) || undefined;

  const {
    mediaUrl, uploading, progress, isDragOver, inputRef, error, clearError,
    handleDragOver, handleDragLeave, handleDrop, handleFileSelect,
    handleDelete, hasResource,
  } = useMediaResource(id, config, onConfigChange, 'file');

  const displayUrl = executionUrl || mediaUrl;
  const rawName = (out?.file_name as string) || (config.file_name as string) || (config.fileName as string);
  const kind: MediaKind = displayUrl
    ? ((out?.type as MediaKind) || detectKind(displayUrl, config.mimeType as string, rawName))
    : 'file';
  const fileName = rawName || (displayUrl ? displayUrl.split('/').pop()?.split('?')[0] : '') || 'file';

  if (!displayUrl) {
    return (
      <div
        className={`w-full h-full flex items-center justify-center rounded-md border-2 border-dashed transition-colors cursor-pointer ${
          error ? 'border-red-500 bg-red-500/10'
            : isDragOver ? 'border-blue-500 bg-blue-500/10'
            : 'border-border dark:border-zinc-700 bg-muted/50 hover:border-border dark:hover:border-zinc-600'
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => { clearError(); inputRef.current?.click(); }}
      >
        <div className="flex flex-col items-center gap-2 px-3 text-center text-muted-foreground/70 dark:text-zinc-600">
          {uploading ? <Loader2 className="w-8 h-8 animate-spin text-blue-600 dark:text-blue-400" />
            : error ? <AlertCircle className="w-8 h-8 text-red-600 dark:text-red-400" />
            : <Upload className="w-8 h-8" />}
          <span className={`text-xs tabular-nums ${error ? 'text-red-600 dark:text-red-400' : ''}`}>
            {uploading
              ? `Uploading… ${Math.round((progress ?? 0) * 100)}%`
              : error ? error : 'Drop a file or click to browse'}
          </span>
          {uploading && <UploadProgressBar fraction={progress ?? 0} className="w-32" />}
        </div>
        {/* accept any file — image, audio, video, pdf, doc, anything */}
        <input ref={inputRef} type="file" className="hidden" onChange={handleFileSelect} />
      </div>
    );
  }

  const deleteBtn = hasResource ? (
    <button
      type="button"
      onClick={handleDelete}
      className="absolute top-1 right-1 z-10 p-1 rounded bg-black/60 text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity"
    >
      <X className="w-3 h-3" />
    </button>
  ) : null;

  if (kind === 'image') {
    return (
      <div className="w-full h-full flex items-center justify-center overflow-hidden rounded-md relative group">
        <ImageView url={displayUrl} alt={(config.alt as string) || fileName} />
        {deleteBtn}
      </div>
    );
  }
  if (kind === 'video') {
    return (
      <div className="w-full h-full flex items-center justify-center bg-background rounded-md overflow-hidden relative group">
        <VideoView url={displayUrl} />
        {deleteBtn}
      </div>
    );
  }
  if (kind === 'audio') {
    return (
      <div className="w-full h-full relative group px-2 flex items-center">
        <AudioView url={displayUrl} />
        {deleteBtn}
      </div>
    );
  }
  if (kind === 'pdf') {
    return (
      <div className="w-full h-full rounded-md overflow-hidden bg-background relative group">
        <iframe src={displayUrl} title={fileName} className="w-full h-full border-0" />
        {deleteBtn}
      </div>
    );
  }
  // Generic file — download card
  return (
    <div className="w-full h-full flex items-center gap-3 px-3 rounded-md border border-border dark:border-zinc-700 bg-card relative group">
      <FileIcon className="w-6 h-6 flex-shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="text-xs text-foreground truncate">{fileName}</div>
        <a href={displayUrl} target="_blank" rel="noopener noreferrer"
          className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center gap-1">
          <Download className="w-3 h-3" /> Open file
        </a>
      </div>
      {deleteBtn}
    </div>
  );
}

function ImageView({ url, alt }: { url: string; alt: string }) {
  const [err, setErr] = useState(false);
  useEffect(() => { setErr(false); }, [url]);
  if (err) return <MediaError label="Could not load this image." />;
  return <img src={url} alt={alt} className="max-w-full max-h-full object-contain" onError={() => setErr(true)} />;
}

function VideoView({ url }: { url: string }) {
  const [err, setErr] = useState(false);
  useEffect(() => { setErr(false); }, [url]);
  if (err) return <MediaError label="Could not load this video." />;
  return <video src={url} controls className="max-w-full max-h-full" onError={() => setErr(true)} />;
}

function AudioView({ url }: { url: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<import('wavesurfer.js').default | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    setLoadError(null);
    let cancelled = false;
    let ws: import('wavesurfer.js').default | null = null;
    import('wavesurfer.js').then(WaveSurfer => {
      if (cancelled || !containerRef.current) return;
      ws = WaveSurfer.default.create({
        container: containerRef.current,
        waveColor: 'hsl(var(--muted-foreground))',
        progressColor: 'hsl(var(--primary))',
        cursorColor: 'hsl(var(--primary))',
        barWidth: 2, barGap: 1, barRadius: 2, height: 'auto', url,
      });
      ws.on('play', () => setIsPlaying(true));
      ws.on('pause', () => setIsPlaying(false));
      ws.on('finish', () => setIsPlaying(false));
      ws.on('error', () => { setIsPlaying(false); setLoadError('Could not load this audio.'); });
      wsRef.current = ws;
    }).catch(() => { if (!cancelled) setLoadError('Could not initialize the audio player.'); });
    return () => { cancelled = true; ws?.destroy(); wsRef.current = null; };
  }, [url]);

  if (loadError) return <MediaError label={loadError} />;
  return (
    <div className="w-full flex items-center gap-2">
      <button
        type="button"
        onClick={() => wsRef.current?.playPause()}
        className="flex-shrink-0 w-7 h-7 rounded-full bg-blue-600 hover:bg-blue-500 flex items-center justify-center transition-colors"
      >
        {isPlaying ? <Pause className="w-3 h-3 text-white" /> : <Play className="w-3 h-3 text-white ml-0.5" />}
      </button>
      <div ref={containerRef} className="flex-1 min-w-0 h-8" />
    </div>
  );
}

function MediaError({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-3 text-xs text-red-600 dark:text-red-400">
      <AlertCircle className="w-4 h-4 flex-shrink-0" />
      <span className="truncate">{label}</span>
    </div>
  );
}
