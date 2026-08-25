// Resources panel for the FlowCanvas "Resources" tab.
// Displays workflow resources as a tile grid with a full-screen preview dialog on click.
// All content rendering is delegated to the reusable ResourceRenderer component.

import { useEffect } from 'react';
import {
  FolderOpen, Trash2, Download, Loader2,
} from 'lucide-react';
import { Dialog, DialogContent } from '~/components/ui/dialog';
import {
  ResourceRenderer, isWidePreview, resolveMediaType,
  getThumbnailConfig, formatSize, formatDate,
} from '~/components/resource/ResourceRenderer';
import { useWorkflowResources } from '~/hooks/useWorkflowResources';
import type { ResourceInfo } from '~/types/socket-events.generated';

// -- Tile Thumbnail -----------------------------------------------------------

function TileThumbnail({ resource, url }: { resource: ResourceInfo; url?: string }) {
  const mediaType = resolveMediaType(resource);
  const thumb = getThumbnailConfig(resource);
  const Icon = thumb.icon;

  if (!url) {
    return (
      <div className={`w-full h-full flex items-center justify-center ${thumb.bg}`}>
        <Icon className={`h-12 w-12 ${thumb.color} opacity-60`} />
      </div>
    );
  }

  // Media types get real inline previews
  if (mediaType === 'image') {
    return <img src={url} alt={resource.name} className="w-full h-full object-cover" loading="lazy" />;
  }
  if (mediaType === 'video') {
    return <video src={url} className="w-full h-full object-cover" muted preload="metadata" />;
  }
  if (mediaType === 'audio') {
    return (
      <div className={`w-full h-full flex flex-col items-center justify-center gap-2 ${thumb.bg}`}>
        <Icon className={`h-10 w-10 ${thumb.color}`} />
        <audio src={url} controls className="w-[85%] h-7" controlsList="nodownload" />
      </div>
    );
  }

  // Non-media: show extension-aware icon thumbnail
  const ext = resource.name.split('.').pop()?.toUpperCase() || '';
  return (
    <div className={`w-full h-full flex flex-col items-center justify-center gap-2 ${thumb.bg}`}>
      <Icon className={`h-12 w-12 ${thumb.color} opacity-70`} />
      {ext && <span className={`text-[11px] font-bold ${thumb.color} opacity-60 uppercase`}>{ext}</span>}
    </div>
  );
}

// -- Resource Tile ------------------------------------------------------------

function ResourceTile({ resource, url, onPreview, onDelete }: {
  resource: ResourceInfo;
  url?: string;
  onPreview: () => void;
  onDelete: () => void;
}) {
  const mediaType = resolveMediaType(resource);
  const thumb = getThumbnailConfig(resource);
  const rowCount = mediaType === 'dataset'
    ? (resource.metadata as Record<string, unknown>)?.row_count
    : null;

  return (
    <div
      className="group relative rounded-xl overflow-hidden border border-border dark:border-white/[0.07] bg-card/60 hover:border-muted-foreground/40 dark:hover:border-white/[0.15] hover:bg-card/80 transition-all duration-200 cursor-pointer flex flex-col"
      onClick={onPreview}
    >
      <div className="relative h-36 overflow-hidden bg-card">
        <TileThumbnail resource={resource} url={url} />
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center gap-2 opacity-0 group-hover:opacity-100">
          {url && mediaType !== 'dataset' && (
            <a
              href={url}
              download={resource.name}
              target="_blank"
              rel="noopener noreferrer"
              onClick={e => e.stopPropagation()}
              className="p-2 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
              title="Download"
            >
              <Download className="h-4 w-4" />
            </a>
          )}
          <button
            type="button"
            onClick={e => { e.stopPropagation(); onDelete(); }}
            className="p-2 rounded-full bg-black/60 text-red-400 hover:bg-red-500/30 transition-colors"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="px-3 py-2.5 flex flex-col gap-1 min-w-0">
        <p className="text-sm text-foreground/80 truncate font-medium" title={resource.name}>
          {resource.name}
        </p>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground dark:text-zinc-500">
          <span className={`${thumb.color} font-medium`}>{thumb.label}</span>
          {rowCount != null && <span>{String(rowCount)} rows</span>}
          {resource.size_bytes ? <span>{formatSize(resource.size_bytes)}</span> : null}
          <span className="ml-auto">{formatDate(resource.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

// -- Preview Dialog -----------------------------------------------------------

function ResourcePreviewDialog({ resource, url, onClose, onDelete }: {
  resource: ResourceInfo | null;
  url?: string;
  onClose: () => void;
  onDelete: (id: string) => void;
}) {
  if (!resource) return null;

  const mediaType = resolveMediaType(resource);
  const thumb = getThumbnailConfig(resource);
  const wide = isWidePreview(resource);

  return (
    <Dialog open={!!resource} onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent className={`${wide ? 'max-w-4xl' : 'max-w-lg'} bg-card border-border dark:border-zinc-700 p-0 gap-0 overflow-hidden [&>button:last-child]:hidden`}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div className="flex items-center gap-2 min-w-0">
            <thumb.icon className={`h-4 w-4 ${thumb.color} shrink-0`} />
            <span className="text-sm text-foreground font-medium truncate">{resource.name}</span>
            <span className="text-[11px] text-muted-foreground dark:text-zinc-500 shrink-0">{formatSize(resource.size_bytes)}</span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {url && mediaType !== 'dataset' && (
              <a
                href={url}
                download={resource.name}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1.5 rounded hover:bg-foreground/10 text-muted-foreground hover:text-foreground transition-colors"
                title="Download"
              >
                <Download className="h-4 w-4" />
              </a>
            )}
            <button
              type="button"
              onClick={() => { onDelete(resource.id); onClose(); }}
              className="p-1.5 rounded hover:bg-red-500/20 text-muted-foreground hover:text-red-600 dark:hover:text-red-400 transition-colors"
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex items-center justify-center bg-black/30 min-h-[200px]">
          <ResourceRenderer resource={resource} url={url} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

// -- Main Component -----------------------------------------------------------

interface WorkflowResourcesProps {
  workflowId: string;
}

export function WorkflowResources({ workflowId }: WorkflowResourcesProps) {
  const {
    resources, loading, fetchResources, urlMap,
    deleteResource,
    previewResource, openPreview, closePreview,
  } = useWorkflowResources(workflowId);

  useEffect(() => {
    fetchResources();
  }, [fetchResources]);

  if (loading && resources.length === 0) {
    return (
      <div className="flex items-center justify-center h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground dark:text-zinc-500" />
      </div>
    );
  }

  if (resources.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-[400px] text-center">
        <FolderOpen className="h-12 w-12 text-muted-foreground dark:text-zinc-500 mb-4" />
        <h3 className="text-lg font-semibold text-foreground mb-2">No resources yet</h3>
        <p className="text-sm text-muted-foreground">
          Resources uploaded to your interface blocks will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full flex flex-col flex-1 min-h-0 overflow-y-auto" style={{ scrollbarWidth: 'thin', scrollbarColor: 'hsl(var(--border) / 0.5) transparent' }}>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 pb-4">
        {resources.map(resource => (
          <ResourceTile
            key={resource.id}
            resource={resource}
            url={urlMap[resource.id]}
            onPreview={() => openPreview(resource)}
            onDelete={() => deleteResource(resource.id)}
          />
        ))}
      </div>

      <ResourcePreviewDialog
        resource={previewResource}
        url={previewResource ? urlMap[previewResource.id] : undefined}
        onClose={closePreview}
        onDelete={deleteResource}
      />
    </div>
  );
}
