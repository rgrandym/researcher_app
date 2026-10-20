import { describe, expect, test } from 'claude-code/testing'

import { parseConf, parseStages, runOf } from '../hooks/register'

const SEARCH_HIT = { query: 'q', results: [], durationSeconds: 0 }
const PANE_PROPS = {
  title: 'Research monitor',
  isFocused: false,
  bodyColumns: 80,
  placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 40 },
  view: {},
}

describe('search budget', () => {
  test('refuses web searches past the cap in monitor.json', async ($, on) => {
    on('session.root', () => ({ value: '/workspace' }))
    on('fs.read', () => ({ value: '{"searchCap": 2}' }))
    on('tool.call', { tool: 'WebSearch' }, () => ({ result: SEARCH_HIT }))

    const first = await $.tool.call({ tool: 'WebSearch', query: 'one', mode: 'standard' })
    const second = await $.tool.call({ tool: 'WebSearch', query: 'two', mode: 'standard' })
    const third = await $.tool.call({ tool: 'WebSearch', query: 'three', mode: 'standard' })

    expect(first.deny).toBeUndefined()
    expect(second.deny).toBeUndefined()
    expect(third.deny ?? third.text ?? '').toMatch(/search cap \(2\) is reached/)
  })

  test('"more" raises the cap for the session', async ($, on) => {
    on('session.root', () => ({ value: '/workspace' }))
    on('fs.read', () => ({ value: '{"searchCap": 1}' }))
    on('tool.call', { tool: 'WebSearch' }, () => ({ result: SEARCH_HIT }))

    await $.tool.call({ tool: 'WebSearch', query: 'one', mode: 'standard' })
    const refused = await $.tool.call({ tool: 'WebSearch', query: 'two', mode: 'standard' })
    const said = await $.command.run({
      command: 'search-budget',
      args: 'more',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 80 },
    })
    const allowed = await $.tool.call({ tool: 'WebSearch', query: 'two', mode: 'standard' })

    expect(refused.deny ?? refused.text ?? '').toMatch(/cap/)
    expect(said.text).toMatch(/Web searches 1 of 101/)
    expect(allowed.deny).toBeUndefined()
  })
})

describe('save check before /user-edits', () => {
  const RUN_TEXT = 'Absorb the edits in outputs/2026-01-01-example-run/report.md'

  test('warns the agent when no save has landed', async ($, on) => {
    on('process.run', () => ({
      value: {
        exitCode: 1,
        stdout: 'NOT SAVED: report.md is not newer than the agent write',
        stderr: '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    }))
    on('session.root', () => ({ value: '/workspace' }))
    on('skill.prompt', (_$, e) => ({ text: e.text }))

    const out = await $.skill.prompt({ skill: 'user-edits', text: RUN_TEXT })

    expect(out.text).toMatch(/^research-monitor ran saved_check\.py on outputs\/2026-01-01-example-run/)
    expect(out.text).toMatch(/Ask the author to save or paste the edit, keep this task pending/)
    expect(out.text).toMatch(/Absorb the edits/)
  })

  test('leaves the skill alone when the save landed', async ($, on) => {
    let ran: readonly string[] = []
    on('process.run', (_$, e) => {
      ran = e.argv
      return { value: { exitCode: 0, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    })
    on('session.root', () => ({ value: '/workspace' }))
    on('skill.prompt', (_$, e) => ({ text: e.text }))

    const out = await $.skill.prompt({ skill: 'user-edits', text: RUN_TEXT })

    expect(out.text).toBe(RUN_TEXT)
    expect(ran).toEqual(['python3', '.claude/scripts/saved_check.py', 'outputs/2026-01-01-example-run'])
  })

  test('ignores other skills', async ($, on) => {
    on('skill.prompt', (_$, e) => ({ text: e.text }))

    const out = await $.skill.prompt({ skill: 'research', text: RUN_TEXT })

    expect(out.text).toBe(RUN_TEXT)
  })
})

describe('pane', () => {
  test('draws on every surface before anything has run', async $ => {
    for (const surface of ['terminal', 'desktop', 'vscode'] as const) {
      const ui = await $.ui.mount({
        plugin: 'research-monitor',
        surface,
        component: 'Pane',
        requestId: 'research-monitor',
        props: PANE_PROPS,
      })
      expect(await ui.find({ text: /No run touched yet/ })).toBeDefined()
      expect(await ui.find({ text: /Web: 0\/400 searches/ })).toBeDefined()
      await ui.unmount()
    }
  })
})

describe('parsing', () => {
  test('reads monitor.json and falls back on bad values', () => {
    const c = parseConf('{"searchCap": 50, "fetchCap": -1, "raise": {"searches": 10}}')
    expect(c.searchCap).toBe(50)
    expect(c.fetchCap).toBe(700)
    expect(c.raise).toEqual({ searches: 10, fetches: 150 })
  })


  test('reads run_check.py lines', () => {
    const stages = parseStages(
      'run: outputs/x\n  ok  prompt    the request, verbatim\n  MISSING critique  critique.md\n\nNOT SHIPPABLE: 1',
    )
    expect(stages).toEqual([
      { status: 'ok', name: 'prompt', detail: 'the request, verbatim' },
      { status: 'MISSING', name: 'critique', detail: 'critique.md' },
    ])
  })

  test('finds the run folder in a path', () => {
    expect(runOf('/a/outputs/2026-01-01-example-run/report.md')).toBe('2026-01-01-example-run')
    expect(runOf('notes about outputs in general')).toBeNull()
  })
})
