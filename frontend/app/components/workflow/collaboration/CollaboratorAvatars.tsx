/**
 * Stacked avatar display for collaborators in the workflow navbar.
 * Shows overlapping avatars with a tooltip listing all connected users.
 * Designed to sit next to the Run button in the AppNavbar rightContent.
 */

import { memo } from 'react';
import { Avatar, AvatarFallback, AvatarImage } from '~/components/ui/avatar';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip';
import type { Collaborator } from '~/lib/collaboration';

interface CollaboratorAvatarsProps {
  collaborators: Collaborator[];
  /** Maximum avatars to show before +N indicator */
  maxVisible?: number;
}

/** Extract initials from a name (e.g., "Alice Chen" -> "AC") */
function getInitials(name: string): string {
  return name
    .split(' ')
    .map(part => part[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

function CollaboratorAvatarsComponent({
  collaborators,
  maxVisible = 3,
}: CollaboratorAvatarsProps) {
  if (collaborators.length === 0) return null;

  const visibleCollaborators = collaborators.slice(0, maxVisible);
  const overflowCount = collaborators.length - maxVisible;

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center -space-x-2 cursor-pointer">
            {visibleCollaborators.map((collaborator, index) => (
              <Avatar
                key={collaborator.id}
                className="h-7 w-7 border-2 border-background dark:border-zinc-900 transition-transform hover:scale-110 hover:z-10 shrink-0"
                style={{
                  zIndex: visibleCollaborators.length - index,
                  boxShadow: `0 0 0 1px ${collaborator.color}`,
                  backgroundColor: collaborator.color,
                }}
              >
                <AvatarImage
                  src={collaborator.avatarUrl}
                  alt={collaborator.name}
                  className="object-cover"
                />
                <AvatarFallback
                  className="text-[10px] font-semibold"
                  style={{ backgroundColor: collaborator.color, color: '#000' }}
                >
                  {getInitials(collaborator.name)}
                </AvatarFallback>
              </Avatar>
            ))}

            {overflowCount > 0 && (
              <div
                className="h-7 w-7 rounded-full bg-secondary dark:bg-zinc-700 border-2 border-background dark:border-zinc-900 flex items-center justify-center text-xs font-medium text-secondary-foreground dark:text-zinc-200"
                style={{ zIndex: 0 }}
              >
                +{overflowCount}
              </div>
            )}
          </div>
        </TooltipTrigger>

        <TooltipContent
          side="bottom"
          align="end"
          sideOffset={14}
          className="bg-card border-border dark:border-zinc-700 p-3 max-w-xs"
        >
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              {collaborators.length} collaborator{collaborators.length !== 1 ? 's' : ''} online
            </p>
            <div className="space-y-1.5">
              {collaborators.map(collaborator => (
                <div
                  key={collaborator.id}
                  className="flex items-center gap-2"
                >
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: collaborator.color }}
                  />
                  <span className="text-sm text-popover-foreground dark:text-zinc-200">
                    {collaborator.name}
                  </span>
                  {!collaborator.isActive && (
                    <span className="text-xs text-muted-foreground dark:text-zinc-500">(away)</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export const CollaboratorAvatars = memo(CollaboratorAvatarsComponent);
