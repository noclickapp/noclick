// The SDK, and its errors as a line a person reads, as the canvas's standards call them (slotStandards.tsx,
// accountStandards.tsx, graph/saves.ts), loaded with their first call. Every reader of a canvas slot imports the
// standards through slots.ts, a host that fills every slot it draws included (a page's preview of a workflow), so they
// import none of the SDK themselves.
export { Connection, stepType, Workflow } from 'noclick';
export { errorText } from '@/screens/console/lib/errorText';
