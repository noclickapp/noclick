// How the buy flow reads where numbers are sold and what a country asks: a country's line in the picker (the kinds that
// need documents said so, and the ones that can't be bought here last), the kind a country opens on (one that can be
// bought, where there is one), and the documents a country asks for in plain words.
import { describe, expect, it } from 'vitest';
import { documentsAsked, documentsSummary } from '~/components/phone/numberDisplay';
import { coverageDetail, openingKind, type CountryCoverage, type NumberRequirement } from '~/hooks/usePhoneNumberPurchase';

const US: CountryCoverage = { country: 'US', number_types: ['local', 'toll_free'], texting_types: ['local'], documents_types: [], steps_types: [] };
// India's local numbers take documents; its mobile ones ask an identity check at the carrier's link.
const IN: CountryCoverage = { country: 'IN', number_types: ['local', 'mobile'], texting_types: [], documents_types: ['local'], steps_types: ['mobile'] };
const MX: CountryCoverage = { country: 'MX', number_types: ['local', 'mobile', 'toll_free'], texting_types: [], documents_types: ['local'], steps_types: [] };
const BR: CountryCoverage = { country: 'BR', number_types: ['local'], texting_types: [], documents_types: ['local'], steps_types: [] };
const SG: CountryCoverage = { country: 'SG', number_types: ['local', 'mobile'], texting_types: [], documents_types: [], steps_types: ['local', 'mobile'] };

describe('coverageDetail', () => {
    it('lists the kinds that can be bought, says which need documents, and the ones that can’t be bought here last', () => {
        expect(coverageDetail(US)).toBe('Local, Toll-free');
        expect(coverageDetail(BR)).toBe('Local · needs documents');
        expect(coverageDetail(MX)).toBe('Local, Mobile, Toll-free · Local needs documents');
        expect(coverageDetail({ ...MX, documents_types: ['local', 'toll_free'] })).toBe('Local, Mobile, Toll-free · Local, Toll-free need documents');
        expect(coverageDetail(IN)).toBe('Local · needs documents · Mobile not sold here yet');
        expect(coverageDetail(SG)).toBe('Local, Mobile · not sold here yet');
    });
});

describe('openingKind', () => {
    it('keeps the kind asked for where it can be bought, documents and all, else opens on one that can', () => {
        expect(openingKind(US, 'local')).toBe('local');
        expect(openingKind(MX, 'local')).toBe('local');
        expect(openingKind(MX, 'toll_free')).toBe('toll_free');
        expect(openingKind(US, 'mobile')).toBe('local');
        expect(openingKind(IN, 'mobile')).toBe('local');
    });

    it('opens a country where nothing can be bought here on the kind asked for, or its first', () => {
        expect(openingKind(SG, 'mobile')).toBe('mobile');
        expect(openingKind(SG, 'toll_free')).toBe('local');
        expect(openingKind(undefined, 'local')).toBe('local');
    });
});

describe('documentsSummary', () => {
    const asked = (kind: NumberRequirement['kind'], name: string): NumberRequirement => ({ id: name, kind, name, description: '', example: '', values: [] });
    // What Telnyx asks before it sells an Indian number (2026-10-10), one requirement listed twice.
    const INDIA = {
        needs: 'steps' as const,
        items: [
            asked('step', 'Company Link (Approved Company Group UUID)'),
            asked('textual', 'Full Name'),
            asked('step', 'Onfido Verification Link - End User'),
            asked('document', 'GST Registration Certificate'),
            asked('document', 'GST Registration Certificate'),
        ],
    };

    it('says what kinds of documents, in plain words', () => {
        expect(documentsSummary(INDIA)).toBe('business registration, tax and identity documents');
        expect(documentsSummary({ needs: 'documents', items: [asked('document', 'Proof of address')] })).toBe('address documents');
        expect(documentsSummary({ needs: 'documents', items: [asked('textual', 'Purpose of use')] })).toBe('documents');
    });

    it('lists each thing asked for once, by its name', () => {
        expect(documentsAsked(INDIA)).toEqual([
            'Company Link (Approved Company Group UUID)',
            'Full Name',
            'Onfido Verification Link - End User',
            'GST Registration Certificate',
        ]);
    });
});
