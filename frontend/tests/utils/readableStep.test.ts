// How a tool call reads in the rehearsal trace.
//
// This is the moment that has to be persuasive to someone who does not write
// software — watching the agent reach for things is most of what makes a
// rehearsal believable. "Calling slack__send_message_to_channel({...})" is a log
// line; "Send message to channel · Slack" is a sentence.

import { describe, it, expect } from 'vitest';
import { readableStep } from '~/hooks/useRehearsal';

describe('readableStep', () => {
    it('reads a provider tool call as an action and a service', () => {
        expect(readableStep('slack__send_message_to_channel')).toEqual({
            label: 'Send message to channel',
            provider: 'Slack',
            tool: 'slack__send_message_to_channel',
        });
    });

    it('uses sentence case, not title case', () => {
        // A list of rows a person reads, not a menu they scan. Title Case On
        // Every Row reads like a spreadsheet.
        expect(readableStep('gmail__fetch_emails_from_inbox').label).toBe(
            'Fetch emails from inbox'
        );
    });

    it('gets brand casing right where title-casing would not', () => {
        expect(readableStep('github__list_repositories').provider).toBe('GitHub');
        expect(readableStep('hubspot__list_pipelines').provider).toBe('HubSpot');
        expect(readableStep('whatsapp__send_text').provider).toBe('WhatsApp');
    });

    it('title-cases an unknown provider rather than leaving it a slug', () => {
        // A provider added later must read correctly with no table entry.
        expect(readableStep('sample_logistics__create_shipment').provider).toBe(
            'Sample Logistics'
        );
        expect(readableStep('some_new_crm__create_deal').provider).toBe('Some New Crm');
    });

    it('handles a bare tool with no provider', () => {
        const step = readableStep('web_search');
        expect(step.label).toBe('Web search');
        expect(step.provider).toBeUndefined();
    });

    it('never renders an empty row', () => {
        // A step frame can arrive before the tool name does; a blank line in the
        // trace reads as the product having lost track of itself.
        expect(readableStep('').label).toBe('Working…');
        expect(readableStep('   ').label).toBe('Working…');
    });

    it('keeps the raw tool name for anything that needs it', () => {
        expect(readableStep('slack__send_message_to_channel').tool).toBe(
            'slack__send_message_to_channel'
        );
    });
});
