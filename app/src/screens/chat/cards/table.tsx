// The chat's own cards, each by what its call answered, in the order they're tried: the first that matches draws. A
// host's cards (`chat.cards.more`) are tried before these.
import { str } from '@/lib/toolCalls';
import { AppTestingAskCard } from '@/screens/work/conversation/AppTesting';
import { BrowserTurnCard, BrowserUseCard } from '@/screens/work/browser/BrowserTurnCard';
import { HandoffReceiptCard } from '../atWork/HandoffReceipt';
import {
    isBrowserAct,
    isBrowserUse,
    isChannelCard,
    isCodingHandOff,
    isConnectLink,
    isDomainServed,
    isMcpServer,
    isModelConnectLink,
    isPaymentLink,
    isPhonePurchaseLink,
    isPlacedCall,
    isPlatformAgent,
    isPlatformApproval,
    isPlatformOperation,
    isWorkflowBuild,
} from './cardMatchers';
import { PlatformChannelCard } from './ChannelCard';
import { McpServerCard } from './McpServerCard';
import { NumberPurchaseLinkCard, PaymentLinkCard } from './moneyLinks';
import { OwnerQuestionCard } from './OwnerQuestionCard';
import { PlacedCallCard } from './PlacedCallCard';
import { ConnectLinkCard, DomainServedCard, ModelConnectLinkCard, PlatformAgentCard, PlatformApprovalCard, PlatformBuildCard, PlatformOperationCard } from './PlatformCards';
import type { CardEntry } from './toolCardRegistry';

export const CARDS: readonly CardEntry[] = [
    // A call NoClick placed, followed live under the turn that placed it.
    { match: isPlacedCall, Card: PlacedCallCard },
    // A browser act, live in the conversation until it settles into its receipt; a turn that opened and read pages
    // itself the same way. Ahead of the operation card, which would otherwise draw an act as any long action.
    { match: isBrowserAct, Card: BrowserTurnCard, whileRunning: true },
    { match: isBrowserUse, Card: BrowserUseCard, whileRunning: true },
    // A purchase or deletion held for the owner.
    { match: isPlatformApproval, Card: PlatformApprovalCard },
    // A question an agent asked the owner, answered in place.
    { match: (call) => call.tool === 'human__ask' && !!str(call.result, 'request_id'), Card: OwnerQuestionCard },
    // A coding agent asking its owner before it turns app testing on.
    { match: (call) => call.tool === 'app_testing' && !!str(call.result, 'request_id'), Card: AppTestingAskCard },
    // A workflow being built, on its canvas.
    { match: isWorkflowBuild, Card: PlatformBuildCard },
    // An agent made or changed; a channel made or an agent put in one, the channel itself.
    { match: isPlatformAgent, Card: PlatformAgentCard },
    { match: isChannelCard, Card: PlatformChannelCard },
    // An MCP server made for the owner's own agent, connected on its card.
    { match: isMcpServer, Card: McpServerCard },
    // A link to connect an account, ahead of the operation it waits on: an AI company's as its plan's sign-in.
    { match: isModelConnectLink, Card: ModelConnectLinkCard },
    { match: isConnectLink, Card: ConnectLinkCard },
    // A link the owner pays, ahead of the operation that waits on them.
    { match: isPaymentLink, Card: PaymentLinkCard },
    // A change handed to an app's coding agent: a receipt once it's done.
    { match: isCodingHandOff, Card: HandoffReceiptCard },
    { match: isPlatformOperation, Card: PlatformOperationCard },
    // An app served at a domain: where the site is now.
    { match: isDomainServed, Card: DomainServedCard },
    // A phone number to pick and buy on its purchase page.
    { match: isPhonePurchaseLink, Card: NumberPurchaseLinkCard },
];
