// Shared class strings for node/edge hover chrome (the floating delete button).
// A leaf module so AnimatedWorkflowEdge — which renders inside the lightweight
// marketing canvas previews — can share the style without importing the full
// withNodeWrapper (whose closure pulls the ~9MB schema registry).

// Visual style shared with the edge delete button. Popover-toned base so it
// reads native to the canvas in either theme while staying distinct from it.
// Red flush on hover. No scale-up — buttons don't grow under the cursor.
export const NODE_DELETE_BTN_CLASSES =
    'w-[25px] h-[25px] rounded-full flex items-center justify-center text-foreground/80 bg-card backdrop-blur-sm border border-border/60 dark:border-zinc-700/60 shadow-[0_2px_8px_rgba(0,0,0,0.4)] transition-colors duration-200 hover:bg-red-500 hover:text-white hover:border-red-400/60 hover:shadow-[0_4px_12px_rgba(0,0,0,0.5)] active:scale-95';
