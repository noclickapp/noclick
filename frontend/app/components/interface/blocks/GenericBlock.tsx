import { getBlockDefinition } from '../blockRegistry';
import type { BlockComponentProps } from '../types';

export function GenericBlock({ id, config }: BlockComponentProps) {
  const def = getBlockDefinition(id.split('-')[0]) ?? getBlockDefinition(config.label?.toLowerCase() ?? '');
  const Icon = def?.icon;

  return (
    <div className="w-full h-full flex items-center justify-center bg-muted/50 border border-dashed border-border dark:border-zinc-700 rounded-md">
      <div className="flex flex-col items-center gap-2 text-muted-foreground/70 dark:text-zinc-600">
        {Icon && <Icon className="w-6 h-6" />}
        <span className="text-xs">{config.label || def?.label || 'Block'}</span>
      </div>
    </div>
  );
}
