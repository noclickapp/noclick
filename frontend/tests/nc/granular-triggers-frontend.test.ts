/**
 * Frontend validation: all new granular trigger operations are visible
 * in the operation dropdown for Linear and GitHub nodes.
 *
 * Uses the same getSchemaInfo + operationOptions path the UI uses —
 * so if this passes, the dropdown renders correctly.
 */
import { nc } from '~/lib/nc';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';

export default async function () {
  // ── helpers ───────────────────────────────────────────────────────────────
  function opsFromSchema(nodeType: string): { value: string; label: string; isTrigger: boolean }[] {
    const info = getSchemaInfo(nodeType);
    if (!info || !info.hasDiscriminator) return [];
    const out: { value: string; label: string; isTrigger: boolean }[] = [];
    for (let i = 0; i < info.options.length; i++) {
      const value = info.discriminator.optionToValue.get(i);
      if (!value) continue;
      const option = info.options[i];
      const resolved = option?.$ref ? info.resolveRef(option.$ref) : option;
      const discField = info.discriminator.fieldName!;
      const opProp = resolved?.properties?.[discField];
      const label = opProp?.title || resolved?.title || value;
      const isTrigger = Boolean(opProp?.['x-is-trigger']);
      out.push({ value, label, isTrigger });
    }
    return out;
  }

  // ── Linear ────────────────────────────────────────────────────────────────
  const linearOps = opsFromSchema('automation-linear');
  const linearValues = linearOps.map(o => o.value);

  const EXPECTED_LINEAR_TRIGGER_OPS = [
    'on_issue_created', 'on_issue_updated', 'on_issue_deleted',
    'on_comment_created', 'on_comment_updated', 'on_comment_deleted',
    'on_project_created', 'on_project_updated', 'on_project_deleted',
  ];
  const REMOVED_LINEAR_OPS = ['on_issue_change', 'on_comment', 'on_project_change'];

  for (const op of EXPECTED_LINEAR_TRIGGER_OPS) {
    nc.assert.truthy(
      linearValues.includes(op),
      `Linear op '${op}' is present in frontend schema`
    );
  }
  for (const op of REMOVED_LINEAR_OPS) {
    nc.assert.falsy(
      linearValues.includes(op),
      `Old Linear op '${op}' is NOT present in frontend schema`
    );
  }

  // All trigger ops should be marked x-is-trigger
  const linearTriggerOps = linearOps.filter(o => EXPECTED_LINEAR_TRIGGER_OPS.includes(o.value));
  for (const op of linearTriggerOps) {
    nc.assert.truthy(
      op.isTrigger,
      `Linear op '${op.value}' has x-is-trigger=true`
    );
  }

  // ── GitHub ─────────────────────────────────────────────────────────────────
  const githubOps = opsFromSchema('automation-github-rest');
  const githubValues = githubOps.map(o => o.value);

  const EXPECTED_GITHUB_TRIGGER_OPS = [
    // Issues — 16 ops
    'on_issue_opened', 'on_issue_edited', 'on_issue_deleted', 'on_issue_pinned',
    'on_issue_unpinned', 'on_issue_closed', 'on_issue_reopened', 'on_issue_assigned',
    'on_issue_unassigned', 'on_issue_labeled', 'on_issue_unlabeled', 'on_issue_locked',
    'on_issue_unlocked', 'on_issue_transferred', 'on_issue_milestoned', 'on_issue_demilestoned',
    // Issue comment
    'on_issue_comment',
    // Pull requests — 22 ops
    'on_pull_request_opened', 'on_pull_request_closed', 'on_pull_request_merged',
    'on_pull_request_edited', 'on_pull_request_labeled', 'on_pull_request_unlabeled',
    'on_pull_request_assigned', 'on_pull_request_unassigned', 'on_pull_request_reopened',
    'on_pull_request_synchronize', 'on_pull_request_review_requested',
    'on_pull_request_review_request_removed', 'on_pull_request_ready_for_review',
    'on_pull_request_converted_to_draft', 'on_pull_request_locked', 'on_pull_request_unlocked',
    'on_pull_request_milestoned', 'on_pull_request_demilestoned', 'on_pull_request_enqueued',
    'on_pull_request_dequeued', 'on_pull_request_auto_merge_enabled', 'on_pull_request_auto_merge_disabled',
    // Releases — 7 ops
    'on_release_published', 'on_release_unpublished', 'on_release_created',
    'on_release_edited', 'on_release_deleted', 'on_release_prereleased', 'on_release_released',
    // Stars — 2 ops
    'on_star_created', 'on_star_deleted',
    // Push
    'on_push',
  ];

  const REMOVED_GITHUB_OPS = ['on_issue', 'on_pull_request', 'on_repository', 'on_release'];

  for (const op of EXPECTED_GITHUB_TRIGGER_OPS) {
    nc.assert.truthy(
      githubValues.includes(op),
      `GitHub op '${op}' is present in frontend schema`
    );
  }
  for (const op of REMOVED_GITHUB_OPS) {
    nc.assert.falsy(
      githubValues.includes(op),
      `Old GitHub op '${op}' is NOT present in frontend schema`
    );
  }

  // All new trigger ops should be marked x-is-trigger
  const githubTriggerOps = githubOps.filter(o => EXPECTED_GITHUB_TRIGGER_OPS.includes(o.value));
  const nonTriggerGithubOps = githubTriggerOps.filter(o => !o.isTrigger);
  nc.assert.equal(
    nonTriggerGithubOps.length,
    0,
    `All GitHub trigger ops have x-is-trigger=true (failing: ${nonTriggerGithubOps.map(o => o.value).join(', ')})`
  );

  // Count checks
  nc.assert.equal(
    EXPECTED_LINEAR_TRIGGER_OPS.filter(op => linearValues.includes(op)).length,
    9,
    'All 9 Linear trigger ops visible'
  );
  nc.assert.equal(
    EXPECTED_GITHUB_TRIGGER_OPS.filter(op => githubValues.includes(op)).length,
    49,
    'All 49 GitHub trigger ops visible'
  );

  // Verify labels are set (not just raw operation string values)
  const linearCreatedOp = linearOps.find(o => o.value === 'on_issue_created');
  nc.assert.truthy(
    linearCreatedOp?.label && linearCreatedOp.label !== 'on_issue_created',
    `Linear 'on_issue_created' has a human-readable label: '${linearCreatedOp?.label}'`
  );
  const githubMergedOp = githubOps.find(o => o.value === 'on_pull_request_merged');
  nc.assert.truthy(
    githubMergedOp?.label && githubMergedOp.label !== 'on_pull_request_merged',
    `GitHub 'on_pull_request_merged' has a human-readable label: '${githubMergedOp?.label}'`
  );

  return {
    linear: {
      totalOps: linearOps.length,
      triggerOps: EXPECTED_LINEAR_TRIGGER_OPS.filter(op => linearValues.includes(op)).length,
      sampleLabels: EXPECTED_LINEAR_TRIGGER_OPS.slice(0, 3).map(op =>
        `${op} → "${linearOps.find(o => o.value === op)?.label}"`
      ),
    },
    github: {
      totalOps: githubOps.length,
      triggerOps: EXPECTED_GITHUB_TRIGGER_OPS.filter(op => githubValues.includes(op)).length,
      sampleLabels: ['on_pull_request_merged', 'on_pull_request_closed', 'on_issue_opened'].map(op =>
        `${op} → "${githubOps.find(o => o.value === op)?.label}"`
      ),
    },
  };
}
