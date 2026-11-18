// `/api/v1/*`: NoClick's API with the app's key (src/server/proxy.server.ts), behind the gate's session check.
import { proxy } from '@/server/proxy.server';
import type { Route } from './+types/api.v1';

export const loader = (args: Route.LoaderArgs) => proxy(args);
export const action = (args: Route.ActionArgs) => proxy(args);
