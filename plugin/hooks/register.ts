// claudestra's plugin: when a session starts, check that the claudestra CLI this plugin pins is installed,
// and say how to install it if not, or install it when the user has turned on `auto_install`; then put
// claudestra's guard and shell completion in place (DESIGN.md §6.5, §10), and remind the user to run
// `claudestra setup` until they have chosen their preferences. The guard is the CLI's own, a PreToolUse hook and deny
// rules in the user's settings, so it holds whether or not this plugin is enabled; the plugin puts it
// back at every session's start once the pinned claudestra is installed, and offers no way to leave it out.
import type { EngineInterface, Register } from 'claude-code'

// The claudestra this plugin pins; a test holds it to plugin.json's version.
export const VERSION = '0.2.2'
export const RELEASE = `git+https://github.com/adityaruplaha/claudestra@v${VERSION}`

// A git source given without a version is pinned to this plugin's, so a machine that installs over SSH
// (`git+ssh://…/claudestra.git`) sets it once and keeps step with every update.
export const pinned = (source: string): string =>
  source.startsWith('git+') && !(source.split('/').pop() ?? '').includes('@') ? `${source}@v${VERSION}` : source

// How uv installs claudestra from a source. A local folder is a checkout someone is developing, so it is
// installed editable, as they would.
export const installArgs = (source: string): string[] => [
  '--force',
  ...(source.startsWith('/') || source.startsWith('~') ? ['--editable'] : []),
  source,
]

// The install command as the user would type it, quoting any argument the shell would split.
const quoted = (arg: string) => (/^[\w@%+=:,./~-]+$/.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`)
export const installCommand = (source: string): string =>
  ['uv', 'tool', 'install', ...installArgs(source)].map(quoted).join(' ')

type Ran = { exitCode: number; stdout: string; stderr: string }

// What the install step needs of the engine, so a test can stand in for it.
export type Io = {
  run: (argv: string[], timeoutMs?: number) => Promise<Ran | undefined>
  status: (text: string | undefined) => void
  toast: (text: string, timeoutMs?: number) => void
}

export const io = ($: EngineInterface): Io => ({
  run: async (argv, timeoutMs = 30_000) => {
    try {
      return await $.process.run(argv, { timeoutMs })
    } catch {
      return undefined // not installed, or ran past its time
    }
  },
  status: text => $.ui.status(text),
  toast: (text, timeoutMs) => $.ui.toast(text, { timeoutMs }),
})

const said = (r: Ran | undefined) => (r === undefined ? 'did not run' : (r.stderr.trim().split('\n').pop() ?? ''))

// The CLI is found through uv's own bin folder, so it need not be on the PATH the session was started with.
// Without `auto_install` the plugin installs nothing: it says what to run, and without the pinned claudestra
// there is nothing to put the guard in place with.
export async function ensure(io: Io, source: string, autoInstall: boolean): Promise<string | undefined> {
  const dir = await io.run(['uv', 'tool', 'dir', '--bin'])
  if (dir?.exitCode !== 0) {
    io.toast('claudestra needs uv (https://docs.astral.sh/uv/) to install it; its guard is not in place')
    return undefined
  }
  const cli = `${dir.stdout.trim()}/claudestra`
  const have = await io.run([cli, '--version'])
  if (have?.exitCode !== 0 || have.stdout.trim() !== VERSION) {
    if (!autoInstall) {
      const found = have?.exitCode === 0 ? `${have.stdout.trim()} is installed` : 'it is not installed'
      const say = `claudestra ${VERSION} is needed and ${found}, so its guard is not in place.`
      io.toast(`${say} Install it with: ${installCommand(source)}`, 30_000)
      return undefined
    }
    io.status(`claudestra: installing ${VERSION}`)
    const got = await io.run(['uv', 'tool', 'install', '--quiet', ...installArgs(source)], 600_000)
    io.status(undefined)
    if (got?.exitCode !== 0) {
      io.toast(`claudestra could not be installed from ${source}: ${said(got)}`)
      return undefined
    }
  }
  const guard = await io.run([cli, 'install', 'guard', '-y'])
  if (guard?.exitCode !== 0) io.toast(`claudestra's guard could not be put in place: ${said(guard)}`)
  await io.run([cli, 'install', 'completion', '-y']) // a convenience; a failure is not worth a toast
  const prefs = await io.run([cli, 'preferences'])
  if (prefs?.exitCode === 0 && prefs.stdout.includes('not chosen'))
    io.toast('claudestra is not set up yet: run `claudestra setup` in a terminal')
  return cli
}

export const register: Register = (on, options) => {
  const source = typeof options.source === 'string' && options.source !== '' ? pinned(options.source) : RELEASE
  const autoInstall = options.auto_install === true
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    // An install can take a while; the session does not wait.
    $.clock.after(0, () => void ensure(io($), source, autoInstall))
    return started
  })
}
