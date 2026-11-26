// The address params Work keeps where you are in (place.ts), for a host that clears or sets them from outside Work.
export const WORK_PARAMS = ['space', 'show', 'channel', 'thread', 'agent', 'panel', 'ptab', 'trigger', 'machine', 'file', 'sub', 'res', 'item'] as const;

/** Work's `channel` for a space's NoClick channel, whichever channel that is: Work opens it once its channels are read. */
export const WORK_NOCLICK_CHANNEL = 'noclick';
