import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgentRow, AgentTally, Conf, Stage, Usage, Web } from '../types'

const P = 'research-monitor'
const PANE = 'research-monitor'
const RUN = /outputs\/(\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+)/
const STAGE = /^ {2}(ok|MISSING)\s+(\S+)\s+(.*)$/
const SAVE_CHECKED = new Set(['user-edits'])
const CONF_DEFAULTS: Conf = { searchCap: 400, fetchCap: 700, warnEvery: 100, raise: { searches: 100, fetches: 150 }, isLoaded: false }
const STAGE_EVERY_MS = 15_000

const web = atom({ plugin: 'research-monitor', key: 'web' } as const, {
  searches: 0,
  fetches: 0,
  extraSearches: 0,
  extraFetches: 0,
  warned: 0,
} as Web)
const tallies = atom({ plugin: 'research-monitor', key: 'tallies' } as const, {} as Record<string, AgentTally>)
const agents = atom({ plugin: 'research-monitor', key: 'agents' } as const, [] as AgentRow[])
const run = atom({ plugin: 'research-monitor', key: 'run' } as const, null as string | null)
const stages = atom({ plugin: 'research-monitor', key: 'stages' } as const, [] as Stage[])
const usage = atom({ plugin: 'research-monitor', key: 'usage' } as const, { windows: [] } as Usage)
const conf = atom({ plugin: 'research-monitor', key: 'conf' } as const, CONF_DEFAULTS)

export function runOf(text: string): string | null {
  return RUN.exec(text)?.[1] ?? null
}

export function parseStages(stdout: string): Stage[] {
  return stdout.split('\n').flatMap(line => {
    const m = STAGE.exec(line)
    return m ? [{ status: m[1] ?? '', name: m[2] ?? '', detail: (m[3] ?? '').trim() }] : []
  })
}

function thousands(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n)
}

type Limits = { searches: number; fetches: number }

let lastStageCheck = 0

export function parseConf(text: string): Conf {
  const raw = JSON.parse(text) as Partial<Conf>
  const num = (v: unknown, d: number) => (typeof v === 'number' && v > 0 ? v : d)
  return {
    searchCap: num(raw.searchCap, CONF_DEFAULTS.searchCap),
    fetchCap: num(raw.fetchCap, CONF_DEFAULTS.fetchCap),
    warnEvery: num(raw.warnEvery, CONF_DEFAULTS.warnEvery),
    raise: {
      searches: num(raw.raise?.searches, CONF_DEFAULTS.raise.searches),
      fetches: num(raw.raise?.fetches, CONF_DEFAULTS.raise.fetches),
    },
    isLoaded: true,
  }
}

// The caps live in .claude/monitor.json, shared with monitor.py for Codex.
async function settings($: EngineInterface): Promise<Conf> {
  const known = await read($, conf)
  if (known.isLoaded) return known
  const root = await $.session.root()
  const text = await $.fs.read(`${root}/.claude/monitor.json`).catch(() => null)
  const loaded = typeof text === 'string' ? parseConf(text) : { ...CONF_DEFAULTS, isLoaded: true }
  await update($, conf, () => loaded)
  return loaded
}

function caps(w: Web, c: Conf): Limits {
  return { searches: c.searchCap + w.extraSearches, fetches: c.fetchCap + w.extraFetches }
}

async function showStatus($: EngineInterface) {
  const w = await read($, web)
  const u = await read($, usage)
  const c = caps(w, await settings($))
  const cost = u.usd === undefined ? '' : ` · $${u.usd.toFixed(2)}`
  $.ui.status(`web ${w.searches}/${c.searches} · fetch ${w.fetches}/${c.fetches}${cost}`)
}

async function tally($: EngineInterface, id: string, add: Partial<AgentTally>) {
  await update($, tallies, all => {
    const one = all[id] ?? { tokensIn: 0, tokensOut: 0, web: 0 }
    return {
      ...all,
      [id]: {
        tokensIn: one.tokensIn + (add.tokensIn ?? 0),
        tokensOut: one.tokensOut + (add.tokensOut ?? 0),
        web: one.web + (add.web ?? 0),
      },
    }
  })
}

async function refreshAgents($: EngineInterface) {
  const list = await $.agent.list()
  await update($, agents, () =>
    list.map(a => ({ id: a.id, type: a.type, description: a.description, status: a.status })).slice(-30),
  )
}

async function refreshStages($: EngineInterface, force: boolean) {
  const name = await read($, run)
  if (name === null) return
  const now = await $.clock.now()
  if (!force && now - lastStageCheck < STAGE_EVERY_MS) return
  lastStageCheck = now
  const root = await $.session.root()
  const ran = await $.process.run(['python3', '.claude/scripts/run_check.py', `outputs/${name}`], {
    cwd: root,
    timeoutMs: 20_000,
  })
  await update($, stages, () => parseStages(ran.stdout))
}

async function newestRun($: EngineInterface) {
  const root = await $.session.root()
  const entries = await $.fs.list(`${root}/outputs`).catch(() => [])
  const dirs = entries.filter(d => d.kind === 'dir' && RUN.test(`outputs/${d.name}`))
  dirs.sort((a, b) => b.mtimeMs - a.mtimeMs)
  return dirs[0]?.name ?? null
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'monitor', description: 'Show agents, pipeline stages, web use and cost in a pane' })
    await $.command.register({
      name: 'search-budget',
      description: 'Show web searches and fetches this session; "more" raises the cap',
      argumentHint: '[more]',
    })
    if (options.pane === 'auto') void $.ui.open({ id: PANE, title: 'Research monitor' })
    void showStatus($)

    return next(e)
  })

  on('command.run', { command: 'monitor' }, async $ => {
    await refreshAgents($)
    await refreshStages($, true)
    await $.ui.open({ id: PANE, title: 'Research monitor' })

    return { text: 'Research monitor opened.' }
  })

  on('command.run', { command: 'search-budget' }, async ($, e) => {
    const settled = await settings($)
    if (e.args.trim() === 'more') {
      await update($, web, w => ({
        ...w,
        extraSearches: w.extraSearches + settled.raise.searches,
        extraFetches: w.extraFetches + settled.raise.fetches,
      }))
    }
    const w = await read($, web)
    const c = caps(w, settled)
    await showStatus($)

    return {
      text: `Web searches ${w.searches} of ${c.searches}, fetches ${w.fetches} of ${c.fetches} this session, all agents together.`,
    }
  })

  on('tool.call', async ($, e, next) => {
    const tool = String(e.tool)
    const isSearch = tool === 'WebSearch'
    const isFetch = tool === 'WebFetch'

    if (isSearch || isFetch) {
      const settled = await settings($)
      const w = await read($, web)
      const c = caps(w, settled)
      if (isSearch ? w.searches >= c.searches : w.fetches >= c.fetches) {
        $.ui.toast(`Web ${isSearch ? 'search' : 'fetch'} cap reached. /search-budget more raises it.`)
        return {
          deny:
            `${P}: this session's web ${isSearch ? 'search' : 'fetch'} cap (${isSearch ? c.searches : c.fetches}) is reached. ` +
            'Do not search or fetch further. Finish the current stage with the evidence already on disk, ' +
            'and register what is still missing as a gap with wanted.py. The author can raise the cap with /search-budget more.',
        }
      }
      await update($, web, x => ({
        ...x,
        searches: x.searches + (isSearch ? 1 : 0),
        fetches: x.fetches + (isFetch ? 1 : 0),
      }))
      await tally($, e.agentId ?? 'main', { web: 1 })
      const after = await read($, web)
      if (isSearch && after.searches >= after.warned + settled.warnEvery) {
        await update($, web, x => ({ ...x, warned: x.warned + settled.warnEvery }))
        $.ui.toast(`${after.searches} web searches this session (cap ${c.searches}).`)
      }
      await showStatus($)
    }

    const input = e as unknown as Record<string, unknown>
    const target = [input.file_path, input.command, input.path].filter(v => typeof v === 'string').join(' ')
    const touched = runOf(target)
    const ran = await next(e)

    if (touched !== null) {
      const changed = (await read($, run)) !== touched
      if (changed) await update($, run, () => touched)
      await refreshStages($, changed)
    }
    if (tool === 'Agent' || tool === 'Task') await refreshAgents($)

    return ran
  }).catch(($, e, next) => next(e))

  on('turn.start', async ($, e, next) => {
    await refreshAgents($)

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const used = e.usage
    if (used !== undefined) {
      await tally($, e.agentId ?? 'main', {
        tokensIn: used.input_tokens + used.cache_read_input_tokens + used.cache_creation_input_tokens,
        tokensOut: used.output_tokens,
      })
    }
    await refreshAgents($)
    await refreshStages($, false)

    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    await update($, usage, () => ({
      usd: e.cost?.usd,
      contextPercent: e.context.percent,
      windows: e.rateLimits.map(r => ({ kind: r.kind, percentUsed: r.percentUsed, resetsAt: r.resetsAt })),
    }))
    await showStatus($)

    return next(e)
  })

  on('skill.prompt', async ($, e, next) => {
    if (!SAVE_CHECKED.has(e.skill)) return next(e)
    const name = runOf(e.text) ?? (await read($, run)) ?? (await newestRun($))
    if (name === null) return next(e)
    const root = await $.session.root()
    const checked = await $.process.run(['python3', '.claude/scripts/saved_check.py', `outputs/${name}`], {
      cwd: root,
      timeoutMs: 20_000,
    })
    if (checked.exitCode === 0) return next(e)

    const said = checked.stdout.trim().split('\n').slice(0, 6).join('\n')
    const notice =
      checked.exitCode === 1
        ? `${P} ran saved_check.py on outputs/${name} before this skill: exit 1, no save has landed since the agent last wrote. ` +
          'Stop. Tell the author to save the document in their editor, and do not read it until they confirm.'
        : `${P} ran saved_check.py on outputs/${name} before this skill: exit ${checked.exitCode}, so whether the author saved cannot be told. ` +
          'Say so to the author before reading their edits.'
    if (checked.exitCode === 1) $.ui.toast('Save your edits in the editor first: /user-edits would read a stale file.')

    return next({ ...e, text: `${notice}\n\n${said}\n\n${e.text}` })
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const w = await read($, web)
    const u = await read($, usage)
    const list = await read($, agents)
    const t = await read($, tallies)
    const name = await read($, run)
    const st = await read($, stages)
    const c = caps(w, await read($, conf))
    const main = t.main ?? { tokensIn: 0, tokensOut: 0, web: 0 }
    const live = list.filter(a => a.status === 'running' || a.status === 'pending' || a.status === 'waiting')
    const done = list.filter(a => !live.includes(a))
    const room = Math.max(3, (e.viewport?.rows ?? 30) - 24)
    const shown = [...live, ...done.slice(-Math.max(0, room - live.length))]

    return (
      <Box flexDirection="column">
        <Text bold>Usage</Text>
        <Text>
          {u.usd === undefined ? 'Cost not reported yet' : `Session cost $${u.usd.toFixed(2)}`}
          {u.contextPercent === undefined ? '' : ` · context ${Math.round(u.contextPercent)}%`}
        </Text>
        {u.windows.map(r => (
          <Text dimColor={r.percentUsed < 80} color={r.percentUsed >= 90 ? 'red' : undefined}>
            {r.kind} {Math.round(r.percentUsed)}%{r.resetsAt ? ` · resets ${r.resetsAt.slice(11, 16)}` : ''}
          </Text>
        ))}
        <Text>
          Web: {w.searches}/{c.searches} searches · {w.fetches}/{c.fetches} fetches
        </Text>

        <Text bold>{'\n'}Agents</Text>
        <Text dimColor>
          main · {thousands(main.tokensIn)} in / {thousands(main.tokensOut)} out · {main.web} web
        </Text>
        {shown.length === 0 && <Text dimColor>No subagents this session.</Text>}
        {shown.map(a => {
          const one = t[a.id] ?? { tokensIn: 0, tokensOut: 0, web: 0 }
          return (
            <Text dimColor={!live.includes(a)} wrap="truncate-end">
              {a.status.padEnd(9)} {a.type} · {a.description} · {thousands(one.tokensIn)} in /{' '}
              {thousands(one.tokensOut)} out · {one.web} web
            </Text>
          )
        })}

        <Text bold>{'\n'}Run</Text>
        {name === null ? (
          <Text dimColor>No run touched yet this session.</Text>
        ) : (
          <Text>{name}</Text>
        )}
        {st.map(s => (
          <Text dimColor={s.status === 'ok'} color={s.status === 'ok' ? undefined : 'yellow'} wrap="truncate-end">
            {s.status === 'ok' ? 'done   ' : 'pending'} {s.name.padEnd(9)} {s.detail}
          </Text>
        ))}
      </Box>
    )
  })
}
