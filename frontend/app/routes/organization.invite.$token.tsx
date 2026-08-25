/**
 * Organization Invite Acceptance Page.
 * A beautiful, focused experience for accepting organization invites.
 * Fetches invite details to show personalized content before accepting.
 */

import { redirect, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData, useNavigate } from 'react-router';
import { useState, useEffect } from 'react';
import { requireAuth } from '~/lib/supabase';
import { useOrganization, type InviteDetails } from '~/hooks/useOrganization';
import { cn } from '~/lib/utils';
import { Loader2, Check, X, ArrowRight, Users } from 'lucide-react';
import { isMemberLimitError } from '~/lib/planLimitErrors';
import { buildSeoMeta } from '~/lib/seo';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Organization Invite - NoClick',
        description: 'Accept your invitation to join a NoClick organization.',
        indexable: false,
    });

// The invite page renders its own custom member-limit UI (not the popup), so we keep
// these tiny parsers local. They mirror the format produced by the org-member trigger.
function extractTierFromError(error: string): 'free' | 'plus' | 'pro' | 'enterprise' {
  const lowerError = error.toLowerCase();
  if (lowerError.includes('plus plan')) return 'plus';
  if (lowerError.includes('pro plan')) return 'pro';
  if (lowerError.includes('enterprise')) return 'enterprise';
  return 'free';
}

function extractLimitFromError(error: string): number {
  const match = error.match(/up to (\d+) members/i);
  return match ? parseInt(match[1], 10) : 3;
}

export async function loader({ request, params }: LoaderFunctionArgs) {
  const { user, headers } = await requireAuth(request);
  const { token } = params;

  if (!token) {
    // Carry the auth headers: requireAuth may have rotated the refresh token.
    throw redirect('/dashboard', { headers });
  }

  return json({ user, token }, { headers });
}

export default function AcceptInvitePage() {
  const { token } = useLoaderData<JsonPayloadOf<typeof loader>>();
  const navigate = useNavigate();
  const { getInviteDetails, acceptInvite, loading, error, clearError } = useOrganization();

  const [status, setStatus] = useState<'loading' | 'ready' | 'accepting' | 'success' | 'error' | 'member_limit'>('loading');
  const [invite, setInvite] = useState<InviteDetails | null>(null);
  const [result, setResult] = useState<{ organizationId: string; organizationName: string } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [memberLimitInfo, setMemberLimitInfo] = useState<{ tier: string; limit: number } | null>(null);

  // Fetch invite details on mount (only once)
  useEffect(() => {
    let mounted = true;

    const fetchDetails = async () => {
      const details = await getInviteDetails(token);
      if (!mounted) return;

      if (details) {
        setInvite(details);
        setStatus('ready');
      } else {
        setStatus('error');
        setErrorMessage('This invite is invalid or has expired');
      }
    };

    fetchDetails();

    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleAccept = async () => {
    setStatus('accepting');
    const res = await acceptInvite(token);

    if (res) {
      setResult(res);
      setStatus('success');
    } else {
      const errorMsg = error || 'Failed to accept invitation';
      if (isMemberLimitError(errorMsg)) {
        // Show special member limit state
        setMemberLimitInfo({
          tier: extractTierFromError(errorMsg),
          limit: extractLimitFromError(errorMsg),
        });
        setStatus('member_limit');
      } else {
        setStatus('error');
        setErrorMessage(errorMsg);
      }
      clearError();
    }
  };

  const goToDashboard = () => {
    navigate('/');
  };

  // Get initials for avatar fallback
  const getInitials = (name: string) => name.slice(0, 2).toUpperCase();

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-5">
      <div className="w-full max-w-[480px]">
        {/* Main Card */}
        <div className="relative overflow-hidden">
          {/* Top accent line */}
          <div className="h-1 bg-foreground" />

          <div className="bg-background border border-foreground/10 border-t-0">
            {/* Loading State */}
            {status === 'loading' && (
              <div className="px-10 py-20 text-center">
                <Loader2 className="w-8 h-8 text-foreground/40 animate-spin mx-auto mb-6" />
                <p className="text-foreground/50 text-sm">Loading invitation...</p>
              </div>
            )}

            {/* Ready State - Show invite details */}
            {status === 'ready' && invite && (
              <>
                {/* Logo Section */}
                <div className="pt-12 pb-8 flex justify-center">
                  <div className={cn(
                    "w-20 h-20 rounded-full border-2 border-foreground/20 flex items-center justify-center overflow-hidden",
                    !invite.organizationIconUrl && "bg-gradient-to-br from-blue-500 to-blue-700"
                  )}>
                    {invite.organizationIconUrl ? (
                      <img
                        src={invite.organizationIconUrl}
                        alt={invite.organizationName}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <span className="text-2xl font-semibold text-white">
                        {getInitials(invite.organizationName)}
                      </span>
                    )}
                  </div>
                </div>

                {/* Content */}
                <div className="px-10 pb-12 text-center">
                  <h1 className="text-[28px] font-semibold text-foreground tracking-tight mb-3">
                    You're Invited
                  </h1>

                  <p className="text-foreground/60 text-[15px] leading-relaxed mb-2">
                    <span className="text-foreground font-medium">{invite.inviterName}</span> has invited you to join
                  </p>

                  <p className="text-foreground text-lg font-medium mb-1">
                    {invite.organizationName}
                  </p>

                  <p className="text-blue-600 dark:text-blue-400 text-sm font-medium mb-10">
                    as {invite.role === 'admin' ? 'an Admin' : 'a Member'}
                  </p>

                  {/* Accept Button */}
                  <button
                    onClick={handleAccept}
                    className={cn(
                      "w-full py-4 px-6 rounded-lg font-semibold text-[15px] transition-all duration-200",
                      "bg-primary text-primary-foreground hover:bg-primary/90",
                      "flex items-center justify-center gap-2"
                    )}
                  >
                    Accept Invitation
                    <ArrowRight className="w-4 h-4" />
                  </button>

                  {/* Decline link */}
                  <button
                    onClick={goToDashboard}
                    className="mt-4 text-foreground/40 text-sm hover:text-foreground/60 transition-colors"
                  >
                    No thanks
                  </button>
                </div>
              </>
            )}

            {/* Accepting State */}
            {status === 'accepting' && (
              <div className="px-10 py-20 text-center">
                <Loader2 className="w-10 h-10 text-foreground animate-spin mx-auto mb-6" />
                <h1 className="text-xl font-semibold text-foreground mb-2">Joining...</h1>
                <p className="text-foreground/50 text-sm">Setting up your access</p>
              </div>
            )}

            {/* Success State */}
            {status === 'success' && result && (
              <>
                <div className="pt-12 pb-8 flex justify-center">
                  <div className="w-20 h-20 rounded-full bg-emerald-500/20 flex items-center justify-center">
                    <Check className="w-10 h-10 text-emerald-600 dark:text-emerald-400" strokeWidth={2.5} />
                  </div>
                </div>

                <div className="px-10 pb-12 text-center">
                  <h1 className="text-[28px] font-semibold text-foreground tracking-tight mb-3">
                    Welcome!
                  </h1>

                  <p className="text-foreground/60 text-[15px] leading-relaxed mb-10">
                    You're now a member of{' '}
                    <span className="text-foreground font-medium">{result.organizationName}</span>
                  </p>

                  <button
                    onClick={goToDashboard}
                    className={cn(
                      "w-full py-4 px-6 rounded-lg font-semibold text-[15px] transition-all duration-200",
                      "bg-primary text-primary-foreground hover:bg-primary/90",
                      "flex items-center justify-center gap-2"
                    )}
                  >
                    Get Started
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </>
            )}

            {/* Error State */}
            {status === 'error' && (
              <>
                <div className="pt-12 pb-8 flex justify-center">
                  <div className="w-20 h-20 rounded-full bg-red-500/20 flex items-center justify-center">
                    <X className="w-10 h-10 text-red-600 dark:text-red-400" strokeWidth={2.5} />
                  </div>
                </div>

                <div className="px-10 pb-12 text-center">
                  <h1 className="text-[28px] font-semibold text-foreground tracking-tight mb-3">
                    Unable to Join
                  </h1>

                  <p className="text-foreground/60 text-[15px] leading-relaxed mb-10">
                    {errorMessage || 'This invitation may have expired or already been used.'}
                  </p>

                  <button
                    onClick={goToDashboard}
                    className={cn(
                      "w-full py-4 px-6 rounded-lg font-semibold text-[15px] transition-all duration-200",
                      "bg-foreground/10 text-foreground hover:bg-foreground/15 border border-foreground/10"
                    )}
                  >
                    Back to Dashboard
                  </button>
                </div>
              </>
            )}

            {/* Member Limit State */}
            {status === 'member_limit' && memberLimitInfo && (
              <>
                <div className="pt-12 pb-8 flex justify-center">
                  <div className="w-20 h-20 rounded-full bg-amber-500/20 flex items-center justify-center">
                    <Users className="w-10 h-10 text-amber-600 dark:text-amber-400" strokeWidth={2} />
                  </div>
                </div>

                <div className="px-10 pb-12 text-center">
                  <h1 className="text-[28px] font-semibold text-foreground tracking-tight mb-3">
                    Team is Full
                  </h1>

                  <p className="text-foreground/60 text-[15px] leading-relaxed mb-4">
                    <span className="text-foreground font-medium">{invite?.organizationName}</span> has reached
                    its member limit of {memberLimitInfo.limit} on the {memberLimitInfo.tier.charAt(0).toUpperCase() + memberLimitInfo.tier.slice(1)} plan.
                  </p>

                  <p className="text-foreground/40 text-sm mb-10">
                    Ask an administrator to review the instance member policy.
                  </p>

                  <button
                    onClick={goToDashboard}
                    className={cn(
                      "w-full py-4 px-6 rounded-lg font-semibold text-[15px] transition-all duration-200",
                      "bg-foreground/10 text-foreground hover:bg-foreground/15 border border-foreground/10"
                    )}
                  >
                    Back to Dashboard
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Bottom accent line */}
          <div className="h-1 bg-foreground" />
        </div>

        {/* Footer */}
        <div className="mt-8 text-center">
          <p className="text-foreground/30 text-xs">
            Powered by NoClick
          </p>
        </div>
      </div>
    </div>
  );
}
