/* Shared card surface style tokens for public marketing pages (integration
   detail, workflow template detail). Kept as full Tailwind class strings
   because arbitrary color values must be statically present in the source
   for the JIT compiler to emit them — they cannot be templated at runtime. */

export const CARD = 'bg-[#0a0a0c] border border-[#1a1a1e]';
export const CARD_HOVER = 'hover:bg-[#101012] hover:border-[#262629]';
export const CARD_ACTIVE = 'bg-[#101012] border-[#262629]';
