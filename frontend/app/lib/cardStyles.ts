/* Shared card surface style tokens for public marketing pages (integration
   detail, workflow template detail). Kept as full Tailwind class strings
   because arbitrary color values must be statically present in the source
   for the JIT compiler to emit them — they cannot be templated at runtime. */

/* Light mode uses the semantic tokens; dark pins the original hexes so the
   marketing look stays pixel-identical (routes layer dark:border-[#1a1a1e]
   islands on top of these — keep the dark values in sync with them). */
export const CARD = 'bg-card border border-border dark:bg-[#0a0a0c] dark:border-[#1a1a1e]';
export const CARD_HOVER = 'hover:bg-muted hover:border-foreground/20 dark:hover:bg-[#101012] dark:hover:border-[#262629]';
export const CARD_ACTIVE = 'bg-muted border-foreground/20 dark:bg-[#101012] dark:border-[#262629]';
