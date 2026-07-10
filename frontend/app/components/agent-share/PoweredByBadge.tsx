// "Powered by NoClick" referral badge on public shared-agent pages — the
// growth loop: every shared agent page links back to NoClick with attribution
// carried in utm params + the link id. Rendered inline in the composer's hint
// row (via AgentChatComposer footerEnd) so it costs no vertical space.

export function PoweredByBadge({ linkId }: { linkId: string }) {
  return (
    <a
      href={`https://noclick.com/?utm_source=agent-share&utm_medium=badge&ref=${encodeURIComponent(linkId)}`}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="agent-share-powered-by"
      className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground/70 hover:text-muted-foreground border border-border hover:border-foreground/20 rounded-full px-2.5 py-1 transition-colors"
    >
      Powered by
      <span className="inline-flex items-center gap-1 font-semibold text-muted-foreground">
        <img src="/logo.svg" alt="" className="w-3 h-3 invert dark:invert-0" aria-hidden />
        NoClick
      </span>
    </a>
  );
}
