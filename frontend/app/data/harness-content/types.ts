/* Shared types for hand-curated, per-harness marketing/SEO content used by the
   /agents pages. Each CLI harness (Claude Code, Codex, OpenCode, OpenClaw,
   Hermes) gets a unique intro, strengths list, and FAQ so the harness hubs and
   the harness×integration connect pages are substantive, not thin/duplicate. */

export interface HarnessFaq {
    question: string;
    answer: string;
}

export interface HarnessContent {
    /** Backend model_type discriminator — must key HARNESS_MODEL_SPECS in
        ~/lib/agentModelMatch (that map supplies the data.config.model value). */
    modelType: string;
    /** URL slug under /agents/<slug>. */
    slug: string;
    /** Display name, e.g. "Claude Code". */
    displayName: string;
    /** Who makes it, e.g. "Anthropic". */
    vendor: string;
    /** One-line positioning used in the hero + meta description. */
    tagline: string;
    /** 2-4 sentence unique intro. Plain text, no markdown. */
    intro: string;
    /** 3-5 strengths / what it's good at, each a short phrase. */
    strengths: string[];
    /** 1-2 sentences on when to reach for this harness as a tool-using agent. */
    whenToUse: string;
    /** Tailwind text-color class for accenting the harness icon/badge. */
    accentColor: string;
    /** 3-5 harness-level FAQ entries. */
    faqs: HarnessFaq[];
}
