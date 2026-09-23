// Run the same credential-policy interaction used by the nc bridge in Chromium.
// This verifies the real component without modifying any account credentials.
import { it } from 'vitest';
import verifyPermissions from '../nc/credential-permissions.test';

it(
    'requires an explicit save and preserves the existing per-credential rules',
    verifyPermissions
);
