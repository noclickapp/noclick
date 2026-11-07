import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '../../app/schemas/nodes/dbt-cloud.json';
import metadata from '../../app/schemas/nodeMeta/dbt-cloud.json';
import { DbtCloudNode } from '~/components/workflow/nodes/integrations/dbt-cloud';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));

describe('dbt Cloud self-registering definition', () => {
    it('connects both token methods through generated metadata', () => {
        expect(DbtCloudNode.type).toBe(metadata.type);
        expect(metadata.providerLabels.dbt_cloud).toBe('dbt Cloud Account');
        expect(metadata.autoSelectCredential).toBe(true);
        expect(metadata.credentialTypes.DbtCloudServiceTokenCredential).toBe('dbt_cloud_service_token');
        expect(metadata.credentialTypes.DbtCloudPersonalAccessTokenCredential).toBe('dbt_cloud_pat');
        for (const def of [schema.$defs.DbtCloudServiceTokenCredential, schema.$defs.DbtCloudPersonalAccessTokenCredential]) {
            expect(def.properties.access_token['ui:widget']).toBe('password');
            expect(def.required).toEqual(expect.arrayContaining(['access_token', 'account_id', 'deployment', 'project_ids', 'allowed_operations']));
        }
    });

    it('keeps bounded read operations and dependent resource parents', () => {
        const operations = Object.keys(schema.properties.config.discriminator.mapping);
        expect(operations).toHaveLength(14);
        expect(operations).toContain('get_run_artifact_summary');
        expect(operations).not.toContain('run_job');
        expect(schema.$defs.DbtCloudGetRunConfig.properties.run_id['x-dynamic-options'].depends_on).toBe('job_id');
        expect(schema.$defs.DbtCloudArtifactSummaryConfig.properties.artifact.enum).toEqual(['manifest.json', 'run_results.json', 'catalog.json']);
    });

    it('renders the provider artwork on the catalog tile', () => {
        const Icon = DbtCloudNode.Icon;
        expect(renderToStaticMarkup(<Icon />)).toContain('src="/icons/dbt-cloud-brand-vector.svg"');
    });
});
