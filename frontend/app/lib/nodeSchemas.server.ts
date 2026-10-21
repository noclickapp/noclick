// Every node schema, registered up front: the server's node catalog (nodeCatalog.server) reads them all
// synchronously. Server-only, so the client keeps loading schemas per type (utils/nodeSchemas).
import { registerNodeSchemaFiles } from '~/utils/nodeSchemas';

registerNodeSchemaFiles(import.meta.glob<Record<string, unknown>>('../schemas/nodes/*.json', { eager: true, import: 'default' }));
