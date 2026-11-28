/**
 * Where a profile's key is kept, as the Python CLI keeps it (`noclick/cli.py`'s `KeychainStore` and `FileStore`), so
 * either CLI reads the login the other made: the OS keychain under the service `noclick` with the profile as its
 * account, or `credentials.json` beside `config.json`, readable only by you.
 *
 * The keychain is reached through each OS's own tool, never a native module: macOS `security`, Linux `secret-tool`
 * (the Secret Service, with the attributes Python's `keyring` writes), Windows PowerShell over the Credential Manager
 * (the targets `keyring` writes: `noclick`, or `<profile>@noclick` beside another profile). A key always goes to the
 * tool on its stdin, never its arguments.
 *
 * `NOCLICK_KEYCHAIN` switches it, the same in both CLIs: `off` (or `file`) keeps every key in the file; a path runs
 * that program in place of the OS's own tool, called as the OS's tool is (a stand-in for tests: the Python CLI's
 * keychain is the `keyring` library, which `PYTHON_KEYRING_BACKEND` points elsewhere). The OS keychain is per user,
 * whatever `HOME` says, so under a test runner (`NODE_TEST_CONTEXT`) the real one is refused unless a test names one.
 */

import { host } from "./host.ts";
import { CommandError } from "./store.ts";

export const KEYCHAIN_SERVICE = "noclick";
export const KEYCHAIN_ENV = "NOCLICK_KEYCHAIN";

/** Whether `NOCLICK_KEYCHAIN` turns the OS keychain off. */
export function keychainOff(value: string | undefined): boolean {
  return value === "off" || value === "file";
}

export interface KeyStore {
  name: "keychain" | "file";
  read(profile: string): string | null;
  write(profile: string, key: string): void;
  delete(profile: string): void;
}

type Ran = { status: number; stdout: string; stderr: string };

function refused(ran: Ran | null, tool: string): never {
  const why = ran ? (ran.stderr.trim() || `${tool} exited ${ran.status}`) : `${tool} isn't installed`;
  throw new CommandError(`The OS keychain refused: ${why}`, { nextStep: "Unlock the keychain and retry, or pass --store file." });
}

/** macOS: a generic password, service `noclick`, account the profile. */
function macos(tool: string): KeyStore {
  const quoted = (text: string) => `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  return {
    name: "keychain",
    read(profile) {
      const ran = host.run(tool, ["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", profile, "-w"]);
      if (ran?.status === 0) return ran.stdout.replace(/\n$/, "");
      if (ran?.status === 44) return null; // no such item
      return refused(ran, "security");
    },
    write(profile, key) {
      // `security -i` reads its command from stdin, so the key never reaches a process listing.
      const ran = host.run(tool, ["-i"], `add-generic-password -U -s ${quoted(KEYCHAIN_SERVICE)} -a ${quoted(profile)} -w ${quoted(key)}\n`);
      if (ran?.status !== 0 || /error|denied/i.test(ran.stderr)) refused(ran, "security");
      // `security -i` can say nothing of a refusal (a keychain that wants a person to unlock it): read it back.
      if (this.read(profile) !== key) refused({ status: 1, stdout: "", stderr: "it didn't keep the key" }, "security");
    },
    delete(profile) {
      const ran = host.run(tool, ["delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", profile]);
      if (ran?.status !== 0 && ran?.status !== 44) refused(ran, "security");
    },
  };
}

/** Linux: the Secret Service, the attributes `keyring` writes (`service`, `username`, `application`). */
function secretService(tool: string): KeyStore {
  const query = (profile: string) => ["service", KEYCHAIN_SERVICE, "username", profile];
  return {
    name: "keychain",
    read(profile) {
      const ran = host.run(tool, ["lookup", ...query(profile)]);
      if (ran?.status === 0) return ran.stdout.replace(/\n$/, "") || null;
      if (ran?.status === 1 && !ran.stderr.trim()) return null; // no such item
      return refused(ran, "secret-tool");
    },
    write(profile, key) {
      const ran = host.run(tool, ["store", "--label", `Password for '${profile}' on '${KEYCHAIN_SERVICE}'`,
        ...query(profile), "application", "Python keyring library"], key);
      if (ran?.status !== 0) refused(ran, "secret-tool");
    },
    delete(profile) {
      const ran = host.run(tool, ["clear", ...query(profile)]);
      if (ran?.status !== 0 && !(ran?.status === 1 && !ran.stderr.trim())) refused(ran, "secret-tool");
    },
  };
}

/** Windows: the Credential Manager through PowerShell's own access to its API, as `keyring` keeps a password. */
const WINDOWS = String.raw`
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Text;
public static class NcCred {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct C { public int Flags; public int Type; public string TargetName; public string Comment;
    public long LastWritten; public int BlobSize; public IntPtr Blob; public int Persist; public int AttributeCount;
    public IntPtr Attributes; public string TargetAlias; public string UserName; }
  [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredReadW(string t, int type, int f, out IntPtr c);
  [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredWriteW(ref C c, int f);
  [DllImport("advapi32", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool CredDeleteW(string t, int type, int f);
  [DllImport("advapi32")] static extern void CredFree(IntPtr c);
  public static string[] Read(string t) {
    IntPtr p; if (!CredReadW(t, 1, 0, out p)) { if (Marshal.GetLastWin32Error() == 1168) return null; throw new Exception("CredRead " + Marshal.GetLastWin32Error()); }
    try { C c = (C)Marshal.PtrToStructure(p, typeof(C)); byte[] b = new byte[c.BlobSize]; Marshal.Copy(c.Blob, b, 0, c.BlobSize);
      return new string[] { c.UserName, Encoding.Unicode.GetString(b) }; } finally { CredFree(p); }
  }
  public static void Write(string t, string u, string secret) {
    byte[] b = Encoding.Unicode.GetBytes(secret); C c = new C(); c.Type = 1; c.TargetName = t; c.UserName = u;
    c.Comment = "Stored using python-keyring"; c.Persist = 3; c.BlobSize = b.Length; c.Blob = Marshal.AllocHGlobal(b.Length);
    try { Marshal.Copy(b, 0, c.Blob, b.Length); if (!CredWriteW(ref c, 0)) throw new Exception("CredWrite " + Marshal.GetLastWin32Error()); }
    finally { Marshal.FreeHGlobal(c.Blob); }
  }
  public static void Delete(string t) { if (!CredDeleteW(t, 1, 0) && Marshal.GetLastWin32Error() != 1168) throw new Exception("CredDelete " + Marshal.GetLastWin32Error()); }
}
'@
$ask = [Console]::In.ReadToEnd() | ConvertFrom-Json
$service = $ask.service; $user = $ask.profile; $compound = "$user@$service"
if ($ask.op -eq 'read') {
  $c = [NcCred]::Read($service)
  if ($c -eq $null -or $c[0] -ne $user) { $c = [NcCred]::Read($compound) }
  if ($c -ne $null) { [Console]::Out.Write($c[1]) } else { exit 44 }
} elseif ($ask.op -eq 'write') {
  $held = [NcCred]::Read($service)
  if ($held -ne $null) { [NcCred]::Write("$($held[0])@$service", $held[0], $held[1]) }
  [NcCred]::Write($service, $user, $ask.key)
} else {
  foreach ($t in @($service, $compound)) { $c = [NcCred]::Read($t); if ($c -ne $null -and $c[0] -eq $user) { [NcCred]::Delete($t) } }
}
`;

function windows(tool: string): KeyStore {
  const call = (ask: Record<string, string>) =>
    host.run(tool, ["-NoProfile", "-NonInteractive", "-Command", WINDOWS], JSON.stringify({ service: KEYCHAIN_SERVICE, ...ask }));
  return {
    name: "keychain",
    read(profile) {
      const ran = call({ op: "read", profile });
      if (ran?.status === 0) return ran.stdout;
      if (ran?.status === 44) return null;
      return refused(ran, "PowerShell");
    },
    write(profile, key) {
      const ran = call({ op: "write", profile, key });
      if (ran?.status !== 0) refused(ran, "PowerShell");
    },
    delete(profile) {
      const ran = call({ op: "delete", profile });
      if (ran?.status !== 0) refused(ran, "PowerShell");
    },
  };
}

const TOOLS: Partial<Record<NodeJS.Platform, string>> = { darwin: "/usr/bin/security", win32: "powershell.exe" };

/** This machine's OS keychain, or null where it has none to keep a key in (a server or container often hasn't), or
 *  `NOCLICK_KEYCHAIN` turned it off. */
export function osKeychain(): KeyStore | null {
  const asked = host.env[KEYCHAIN_ENV];
  if (keychainOff(asked)) return null;
  if (!asked && process.env.NODE_TEST_CONTEXT) {
    throw new Error(`A test reached the real OS keychain, which is per user whatever HOME says: set ${KEYCHAIN_ENV}=off, `
      + "or to a stand-in program, and give host.run a stand-in.");
  }
  const platform = host.platform;
  const tool = asked || TOOLS[platform] || "secret-tool";
  if (platform === "darwin") return host.run(tool, ["help"]) ? macos(tool) : null;
  if (platform === "win32") return host.run(tool, ["-NoProfile", "-NonInteractive", "-Command", "exit 0"])?.status === 0 ? windows(tool) : null;
  // A Secret Service answers a lookup (found or not: status 0, or 1 saying nothing); no D-Bus or none running, it says why.
  const probe = host.run(tool, ["lookup", "service", KEYCHAIN_SERVICE, "username", "noclick-probe"]);
  return probe && (probe.status === 0 || (probe.status === 1 && !probe.stderr.trim())) ? secretService(tool) : null;
}
