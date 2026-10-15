// The plugin's install step against stand-ins for uv and claudestra: it installs only a claudestra
// other than the one it pins, puts the guard back every time, and says so when it cannot.
import { expect, test } from 'claude-code/testing'
import { ensure, type Io, RELEASE, VERSION } from '../hooks/register'

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

test('installs a claudestra other than the one it pins, then puts the guard in place', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: '0.0.1\n' },
    'uv tool install': { exitCode: 0 },
    '/b/claudestra install-guard -y': { exitCode: 0 },
  })
  expect(await ensure(s.io, RELEASE)).toBe('/b/claudestra')
  expect(s.ran).toEqual([
    'uv tool dir --bin',
    '/b/claudestra --version',
    `uv tool install --force --quiet ${RELEASE}`,
    '/b/claudestra install-guard -y',
  ])
  expect(s.toasts).toEqual([])
})

test('the pinned claudestra is not reinstalled, and the guard goes back all the same', async () => {
  const s = standIns({
    'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' },
    '/b/claudestra --version': { exitCode: 0, stdout: `${VERSION}\n` },
    '/b/claudestra install-guard -y': { exitCode: 0 },
  })
  await ensure(s.io, RELEASE)
  expect(s.ran).toEqual(['uv tool dir --bin', '/b/claudestra --version', '/b/claudestra install-guard -y'])
})

test('without uv it says the guard is not in place', async () => {
  const s = standIns({})
  expect(await ensure(s.io, RELEASE)).toBeUndefined()
  expect(s.toasts.join()).toContain('needs uv')
})

test('a failed install is said, and nothing more is run', async () => {
  const s = standIns({ 'uv tool dir --bin': { exitCode: 0, stdout: '/b\n' }, 'uv tool install': { exitCode: 1 } })
  expect(await ensure(s.io, '/src/claudestra')).toBeUndefined()
  expect(s.ran.at(-1)).toBe('uv tool install --force --quiet /src/claudestra')
  expect(s.toasts.join()).toContain('could not be installed from /src/claudestra')
})
