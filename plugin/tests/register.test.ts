// The plugin's install step against stand-ins for uv and claudestra. By default it installs nothing and
// says what to run; with auto_install it installs only a claudestra other than the one it pins. Either
// way it puts the guard back whenever the pinned claudestra is there, and says so when it cannot.
import { expect, test } from 'claude-code/testing'
import { ensure, type Io, installCommand, pinned, RELEASE, VERSION } from '../hooks/register'

function standIns(answers: Record<string, { exitCode: number; stdout?: string }>) {
  const ran: string[] = []
  const toasts: string[] = []
  const io: Io = {
    run: async argv => {
      const line = argv.join(' ')
      ran.push(line)
      const key = Object.keys(answers).find(k => line.startsWith(k))
      if (key === undefined) return undefined // not installed
      const a = answers[key]!
      return { exitCode: a.exitCode, stdout: a.stdout ?? '', stderr: a.exitCode ? 'failed' : '' }
    },
    status: () => {},
    toast: text => void toasts.push(text),
  }
  return { io, ran, toasts }
}

test('with auto_install, it installs a claudestra other than the one it pins, then puts the guard in place', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: '0.0.1\n' },
    'uv tool install': { exitCode: 0 },
    '/b/claudestra install guard -y': { exitCode: 0 },
  })
  expect(await ensure(s.io, RELEASE, true)).toBe('/b/claudestra')
  expect(s.ran).toEqual([
    'uv tool dir --bin',
    '/b/claudestra --version',
    `uv tool install --quiet --force ${RELEASE}`,
    '/b/claudestra install guard -y',
    '/b/claudestra install completion -y',
    '/b/claudestra preferences',
  ])
  expect(s.toasts).toEqual([])
})

test('the pinned claudestra is not reinstalled, and the guard goes back all the same', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: `${VERSION}\n` },
    '/b/claudestra install guard -y': { exitCode: 0 },
  })
  for (const autoInstall of [false, true]) {
    s.ran.length = 0
    expect(await ensure(s.io, RELEASE, autoInstall)).toBe('/b/claudestra')
    expect(s.ran.slice(0, 3)).toEqual(['uv tool dir --bin', '/b/claudestra --version', '/b/claudestra install guard -y'])
  }
  expect(s.toasts).toEqual([])
})

test('until the user has chosen their preferences, it reminds them to run setup', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: `${VERSION}\n` },
    '/b/claudestra install guard -y': { exitCode: 0 },
    '/b/claudestra install completion -y': { exitCode: 0 },
    '/b/claudestra preferences': { exitCode: 0, stdout: 'fan-out-model: -  (not chosen, so ask the user)\n' },
  })
  await ensure(s.io, RELEASE, false)
  expect(s.toasts.join()).toContain('claudestra setup')
})

test('without uv it says the guard is not in place', async () => {
  const s = standIns({})
  expect(await ensure(s.io, RELEASE, false)).toBeUndefined()
  expect(s.toasts.join()).toContain('needs uv')
})

test('without auto_install, a missing claudestra is not installed, and the toast gives the command', async () => {
  const s = standIns({ 'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' } })
  expect(await ensure(s.io, RELEASE, false)).toBeUndefined()
  expect(s.ran).toEqual(['uv tool dir --bin', '/b/claudestra --version'])
  expect(s.toasts).toEqual([
    `claudestra ${VERSION} is needed and it is not installed, so its guard is not in place. Install it with: uv tool install --force ${RELEASE}`,
  ])
})

test('without auto_install, another version is left alone, and nothing more is run', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: '0.0.1\n' },
  })
  expect(await ensure(s.io, '/src/claudestra', false)).toBeUndefined()
  expect(s.ran).toEqual(['uv tool dir --bin', '/b/claudestra --version'])
  expect(s.toasts.join()).toContain('0.0.1 is installed')
  expect(s.toasts.join()).toContain('Install it with: uv tool install --force --editable /src/claudestra')
})

test('the install command quotes what the shell would split', async () => {
  expect(installCommand("/home/u/my src/it's")).toBe(`uv tool install --force --editable '/home/u/my src/it'\\''s'`)
  expect(installCommand(RELEASE)).toBe(`uv tool install --force ${RELEASE}`)
})

test('with auto_install, a failed install is said, and nothing more is run', async () => {
  const s = standIns({ 'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' }, 'uv tool install': { exitCode: 1 } })
  expect(await ensure(s.io, '/src/claudestra', true)).toBeUndefined()
  expect(s.ran.at(-1)).toBe('uv tool install --quiet --force --editable /src/claudestra')
  expect(s.toasts.join()).toContain('could not be installed from /src/claudestra')
})

test('a git source without a version is pinned to the plugin\'s, and any other source is left as given', async () => {
  expect(pinned('git+ssh://git@github.com/o/claudestra.git')).toBe(`git+ssh://git@github.com/o/claudestra.git@v${VERSION}`)
  expect(pinned('git+ssh://git@github.com/o/claudestra.git@v0.1.0')).toBe('git+ssh://git@github.com/o/claudestra.git@v0.1.0')
  expect(pinned('/home/u/src/claudestra')).toBe('/home/u/src/claudestra')
})
