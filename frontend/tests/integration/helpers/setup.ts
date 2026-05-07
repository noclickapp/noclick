// Global setup for browser-mode integration tests.
// Loaded by every test file via vitest config's `setupFiles`.
//
// Imports the same CSS root.tsx loads in production so the chat surface
// renders with its real Tailwind utilities + custom styles. Without
// this, the rendered UI looks unstyled / primitive.

import '~/tailwind.css';
import '~/styles/button-3d.css';
