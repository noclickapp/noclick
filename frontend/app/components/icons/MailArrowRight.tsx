/**
 * Envelope with a right arrow at the bottom-right — the "send email" mark.
 * Lucide has no mail-with-arrow variant, so this reuses MailPlus's envelope
 * paths with the plus swapped for an arrow; createLucideIcon keeps size,
 * stroke, and className props identical to the other lucide node icons.
 */
import { createLucideIcon } from 'lucide-react';

export const MailArrowRight = createLucideIcon('MailArrowRight', [
    ['path', { d: 'M22 13V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12c0 1.1.9 2 2 2h8', key: 'envelope' }],
    ['path', { d: 'm22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7', key: 'flap' }],
    ['path', { d: 'M16 19h6', key: 'arrow-shaft' }],
    ['path', { d: 'm19 16 3 3-3 3', key: 'arrow-head' }],
]);
