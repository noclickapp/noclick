/** What each curated command runs, by its path in the manifest; `main` registers them all. A path the manifest
 *  doesn't list is refused there, so this can't drift from the Python CLI's commands. */

import * as auth from "./auth.ts";
import * as configure from "./configure.ts";
import type { Run } from "./kit.ts";
import * as operate from "./operate.ts";
import * as ship from "./ship.ts";

export const RUNNERS: Record<string, Run> = {
  signup: auth.signup,
  setup: auth.setup,
  login: auth.login,
  whoami: auth.whoami,
  logout: auth.logout,
  deploy: ship.deploy,
  link: ship.link,
  unlink: ship.unlink,
  status: ship.status,
  open: ship.open,
  releases: ship.releases,
  rollback: ship.rollback,
  promote: ship.promote,
  delete: ship.deleteApp,
  "secret set": configure.secretSet,
  "secret ls": configure.secretLs,
  "secret rm": configure.secretRm,
  "env set": configure.envSet,
  "env ls": configure.envLs,
  "env rm": configure.envRm,
  "settings list": configure.settingsList,
  "settings set": configure.settingsSet,
  "settings delete": configure.settingsDelete,
  bind: configure.bind,
  "domains add": configure.domainAdd,
  "domains ls": configure.domainLs,
  "domains search": configure.domainsSearch,
  "domains buy": configure.domainsBuy,
  "db query": operate.dbQuery,
  "db create": configure.dbCreate,
  "bucket create": configure.bucketCreate,
  logs: operate.logs,
  estimate: operate.estimateCmd,
  "ops wait": operate.opsWait,
  "agents send": operate.agentsSend,
};
