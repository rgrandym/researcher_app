import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentRow, MainRow, Status } from '../types'

// The research workspace's live pane, for Claude Code sessions in VS Code (and the
// terminal). It shows what the app's activity panel shows, and does what the app does by
// itself: absorbs the author's hand edits (/user-edits) and re-exports stale HTML.
// Everything it reads about the runs comes from .claude/scripts/live_status.py.
//
// Inside the Research app the app does both jobs itself, so the mod stays out of the way
// there (the app starts Claude Code with RESEARCH_APP=1).

const PANE = 'research-live'
const POLL_MS = 3000
const SPIN_MS = 400
const SPIN = ['◐', '◓', '◑', '◒']

const status = atom({ plugin: 'research-live', key: 'status' } as const, null as Status | null)
const agents = atom({ plugin: 'research-live', key: 'agents' } as const, [] as AgentRow[])
const main = atom({ plugin: 'research-live', key: 'main' } as const, { isRunning: false, started: null, calls: 0, last: '' } as MainRow)
const frame = atom({ plugin: 'research-live', key: 'frame' } as const, 0)
const since = atom({ plugin: 'research-live', key: 'since' } as const, 0)
const handled = atom({ plugin: 'research-live', key: 'handled' } as const, {} as Record<string, number>)
const note = atom({ plugin: 'research-live', key: 'note' } as const, '')

const now = () => Date.now() / 1000

const elapsed = (from: number, to: number) => {
  const s = Math.max(0, Math.round(to - from))
  return s >= 60 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s` : `${s}s`
}

const clip = (text: string, n: number) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

const KINDS: [RegExp, string][] = [
  [/scout/i, 'Scout'],
  [/verif/i, 'Verifier'],
  [/critic/i, 'Critic'],
  [/writer/i, 'Writer'],
  [/explore|plan/i, 'Explorer'],
]
const kindOf = (type: string) => KINDS.find(([re]) => re.test(type))?.[1] ?? type

let polling = false
let exporting = false

// One look at the runs: refresh the pane, then act on what the author left.
async function poll($: EngineInterface, root: string): Promise<void> {
  if (polling) return
  polling = true
  try {
    const m = await read($, main)
    const argv = ['python3', `${root}/.claude/scripts/live_status.py`, 'status', '--since', String(await read($, since))]
    if (m.isRunning) argv.push('--running')
    const out = await $.process.run(argv, { cwd: root, timeoutMs: 20_000 })
    if (out.exitCode !== 0) return
    const s = JSON.parse(out.stdout) as Status
    await update($, status, () => s)
    if (m.isRunning) return
    const done = await read($, handled)

    const edit = s.pending_edit
    const editKey = edit ? `edit:${edit.run}/${edit.file}` : ''
    if (edit && done[editKey] !== edit.mtime) {
      await update($, handled, h => ({ ...h, [editKey]: edit.mtime }))
      const claimed = await $.process.run(
        ['python3', `${root}/.claude/scripts/live_status.py`, 'claim', edit.run, edit.file, String(edit.mtime)],
        { cwd: root },
      )
      if (claimed.exitCode !== 0) return // the Research app took this save
      const when = new Date(edit.mtime * 1000).toTimeString().slice(0, 5)
      await update($, note, () => `Absorbing your edit to ${edit.run}/${edit.file}`)
      void $.prompt.submit({
        text:
          `/user-edits outputs/${edit.run}/${edit.file} was saved by hand at ${when} and no agent ` +
          'has absorbed the edit yet. Absorb it. (Started automatically by the research-live mod.)',
      })
      return
    }

    if (exporting) return
    for (const x of s.stale_exports) {
      const key = `export:${x.run}/${x.style}`
      if (done[key] === x.mtime) continue
      await update($, handled, h => ({ ...h, [key]: x.mtime }))
      exporting = true
      await update($, note, () => `Re-exporting ${x.run} HTML (${x.style})…`)
      const r = await $.process.run(
        ['python3', `${root}/.claude/scripts/live_status.py`, 'export', x.run, x.style],
        { cwd: root, timeoutMs: 180_000 },
      ).catch(() => null)
      exporting = false
      const ok = r?.exitCode === 0
      await update($, note, () =>
        ok ? `HTML re-exported: ${x.run} (${x.style})` : `HTML export failed for ${x.run}: ${clip(r?.stderr.trim() ?? 'timed out', 120)}`,
      )
      break
    }
  } catch {
    // A bad poll waits for the next one.
  } finally {
    polling = false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const ran = await next(e)
    if ((await $.env.get('RESEARCH_APP')) === '1') return ran
    const root = await $.session.cwd()
    if ((await $.process.run(['test', '-f', `${root}/.claude/scripts/live_status.py`])).exitCode !== 0) return ran
    // Only saves made from now on count as edits to absorb: an older one is the author's call.
    await update($, since, () => now())
    void $.ui.open({ id: PANE, title: 'Research' })
    $.clock.every(POLL_MS, () => void poll($, root))
    $.clock.every(SPIN_MS, () => {
      void read($, main).then(m => (m.isRunning ? update($, frame, f => (f + 1) % SPIN.length) : undefined))
    })
    void poll($, root)
    return ran
  })

  on('turn.start', async ($, e, next) => {
    await update($, main, m => (m.isRunning ? m : { isRunning: true, started: now(), calls: 0, last: '' }))
    // Reopen the pane if the author closed it: a starting turn is when progress counts.
    const panes = await $.ui.panes().catch(() => [{ id: PANE }])
    if ((await read($, since)) > 0 && !panes.some(p => p.id === PANE)) void $.ui.open({ id: PANE, title: 'Research' })
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!e.agentId) await update($, main, m => ({ ...m, isRunning: false }))
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    if (e.agentId) return next(e)
    // A built-in tool's arguments are fields of the event itself.
    const input = e as unknown as { description?: string; subagent_type?: string; command?: string; file_path?: string; query?: string }
    const last = `${e.tool}${input.description || input.command || input.file_path || input.query ? `: ${input.description ?? input.command ?? input.file_path ?? input.query}` : ''}`
    await update($, main, m => ({ ...m, calls: m.calls + 1, last }))
    if (e.tool !== 'Agent') return next(e)
    const id = e.tool_use_id ?? String(now())
    const row: AgentRow = {
      id,
      type: input.subagent_type ?? 'general-purpose',
      description: input.description ?? '',
      status: 'running',
      started: now(),
      ended: null,
    }
    await update($, agents, list => [...list, row].slice(-12))
    const ran = await next(e)
    const failed = Boolean(ran.deny) || ran.isError === true
    await update($, agents, list =>
      list.map((a): AgentRow => (a.id === id ? { ...a, status: failed ? 'failed' : 'done', ended: now() } : a)),
    )
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, status)
    const m = await read($, main)
    const list = await read($, agents)
    const spin = SPIN[await read($, frame)]
    const msg = await read($, note)
    const width = Math.max(30, e.props.bodyColumns ?? 60)
    const t = now()
    const run = s?.run
    const current = run ? run.steps.findIndex(st => !st.done) : -1

    return (
      <Box flexDirection="column">
        {!run && <Text dimColor>No run folder yet.</Text>}
        {run && (
          <Box flexDirection="column">
            <Text bold>{clip(run.name, width)}</Text>
            {run.round && <Text color="claude">expansion {run.round}</Text>}
            <Box flexDirection="row" marginTop={1}>
              {run.steps.map((st, i) => (
                <Text
                  color={st.done ? 'success' : i === current ? 'claude' : undefined}
                  dimColor={!st.done && i !== current}
                  bold={i === current}
                >
                  {i > 0 ? ' ─ ' : ''}
                  {st.done ? '●' : i === current ? (m.isRunning ? spin : '◉') : '○'} {st.label}
                </Text>
              ))}
            </Box>
            <Text dimColor>
              {run.evidence} evidence rows · {run.notes} notes{run.round ? ' this round' : ''}
              {current < 0 ? ' · complete' : ''}
            </Text>
          </Box>
        )}
        <Box flexDirection="column" marginTop={1}>
          <Text bold>Agents</Text>
          <Text color={m.isRunning ? 'claude' : undefined} dimColor={!m.isRunning}>
            {m.isRunning ? spin : '·'} Main thread {m.isRunning ? 'running' : 'idle'}
            {m.started ? ` · ${elapsed(m.started, m.isRunning ? t : m.started)}` : ''}
            {m.calls ? ` · ${m.calls} calls` : ''}
          </Text>
          {m.isRunning && m.last && <Text dimColor>  {clip(m.last, width - 2)}</Text>}
          {list.map(a => (
            <Text
              color={a.status === 'running' ? 'claude' : a.status === 'failed' ? 'error' : 'success'}
              dimColor={a.status === 'done'}
            >
              {a.status === 'running' ? spin : a.status === 'failed' ? '✗' : '✓'} {kindOf(a.type)} · {elapsed(a.started, a.ended ?? t)} ·{' '}
              {clip(a.description, Math.max(10, width - 24))}
            </Text>
          ))}
        </Box>
        {msg && (
          <Box marginTop={1}>
            <Text dimColor>{clip(msg, width)}</Text>
          </Box>
        )}
      </Box>
    )
  })
}
