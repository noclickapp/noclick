// Subtle row of integration logos on the public shared-agent page showing
// which tools the agent can use. Icons arrive pre-serialized from the SSR
// loader (nodeCatalog.server) so the public bundle never imports the node
// registry.

import { SerializedIcon } from '~/components/shared/SerializedIcon';

export interface ToolLogo {
  node_type: string;
  label: string;
  iconHtml: string;
  iconColor: string;
}

export function ToolLogosRow({ tools }: { tools: ToolLogo[] }) {
  if (tools.length === 0) return null;
  return (
    <div
      data-testid="agent-share-tools"
      className="flex items-center gap-3 flex-wrap"
      aria-label="Tools this agent can use"
    >
      <span className="text-[10px] uppercase tracking-wider text-zinc-600">Tools</span>
      {tools.map(tool => (
        <span
          key={tool.node_type + tool.label}
          title={tool.label}
          className="opacity-50 grayscale hover:grayscale-0 hover:opacity-100 transition"
        >
          <SerializedIcon html={tool.iconHtml} iconColor={tool.iconColor} className="w-4 h-4" />
        </span>
      ))}
    </div>
  );
}
