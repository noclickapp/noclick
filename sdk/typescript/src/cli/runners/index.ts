/** What each curated command runs, by its path in the manifest; `main` registers them all. A path the manifest
 *  doesn't list is refused there, so this can't drift from the Python CLI's commands. */

import * as account from "./account.ts";
import * as agents from "./agents.ts";
import * as auth from "./auth.ts";
import * as configure from "./configure.ts";
import * as data from "./data.ts";
import { init } from "./init.ts";
import type { Run } from "./kit.ts";
import * as live from "./live.ts";
import * as machines from "./machines.ts";
import * as move from "./move.ts";
import * as operate from "./operate.ts";
import { resources } from "./resources.ts";
import { shell } from "./shell.ts";
import * as ship from "./ship.ts";
import * as teach from "./teach.ts";

export const RUNNERS: Record<string, Run> = {
  "agents list": agents.agentsList,
  "agents chat": agents.agentsChat,
  "agents move redeem": move.redeem,
  "agents move status": move.status,
  "agents move source": move.source,
  "agents move session": move.session,
  "agents move repo": move.repo,
  "agents move file": move.file,
  "agents move consent": move.consent,
  "agents move secret": move.secret,
  "agents move setup": move.setup,
  "agents move checkout": move.checkout,
  "agents move plan-link": move.planLink,
  "agents move mcp": move.mcp,
  "agents move skill": move.skill,
  "agents move memory": move.memory,
  "agents move note": move.note,
  "agents move instructions": move.instructions,
  "agents move finish": move.finish,
  "machines ssh": machines.machinesSsh,
  "users list": agents.usersList,
  "users create": agents.usersCreate,
  "db shell": data.dbShell,
  "bucket ls": data.bucketLs,
  "bucket cp": data.bucketCp,
  "webhooks listen": machines.webhooksListen,
  live: live.liveStart,
  "live start": live.liveStart,
  "live status": live.liveStatus,
  "live push": live.livePush,
  "live end": live.liveEnd,
  wait: operate.wait,
  init,
  docs: teach.docs,
  skill: teach.skill,
  mcp: teach.mcp,
  signup: auth.signup,
  setup: auth.setup,
  login: auth.login,
  whoami: auth.whoami,
  logout: auth.logout,
  "profile list": account.profileList,
  "profile use": account.profileUse,
  "profile show": account.profileShow,
  completion: account.completionCmd,
  dashboard: account.dashboard,
  changelog: account.changelogCmd,
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
  bind: configure.bind,
  "domains add": configure.domainAdd,
  "domains ls": configure.domainLs,
  "domains search": configure.domainsSearch,
  "domains buy": configure.domainsBuy,
  "db query": operate.dbQuery,
  "db create": configure.dbCreate,
  "bucket create": configure.bucketCreate,
  logs: operate.logs,
  resources,
  estimate: operate.estimateCmd,
  "agents send": operate.agentsSend,
  shell,
};
