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
      className="inline-flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 border border-zinc-800 hover:border-zinc-700 rounded-full px-2.5 py-1 transition-colors"
    >
      Powered by
      <span className="inline-flex items-center gap-1 font-semibold text-zinc-300">
        <img src="/logo.svg" alt="" className="w-3 h-3" aria-hidden />
        NoClick
      </span>
    </a>
  );
}
