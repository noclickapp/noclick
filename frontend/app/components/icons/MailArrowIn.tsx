/**
 * Envelope with a right arrow entering at the bottom-left — the "get email"
 * (inbound trigger) mark. Horizontal mirror of MailArrowRight's envelope with
 * the same right-pointing arrow, so mail flows in on the left and out on the
 * right across the two icons.
 */
import { createLucideIcon } from 'lucide-react';

export const MailArrowIn = createLucideIcon('MailArrowIn', [
    ['path', { d: 'M2 13V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12c0 1.1-.9 2-2 2h-8', key: 'envelope' }],
    ['path', { d: 'm2 7 8.97 5.7a1.94 1.94 0 0 0 2.06 0L22 7', key: 'flap' }],
    ['path', { d: 'M2 19h6', key: 'arrow-shaft' }],
    ['path', { d: 'm5 16 3 3-3 3', key: 'arrow-head' }],
]);
