import { describe, expect, it } from 'vitest';
import { serializeForInlineScript } from './inlineScript.server';

describe('serializeForInlineScript', () => {
    it('produces valid JSON without an executable script terminator', () => {
        const message =
            "quote ' slash \\ </script><script>alert(1)</script>\u2028next";
        const serialized = serializeForInlineScript({ message });

        expect(serialized).not.toContain('</script>');
        expect(JSON.parse(serialized)).toEqual({ message });
    });
});
