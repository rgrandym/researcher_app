import { describe, expect, test } from 'claude-code/testing'

const PANE = {
  component: 'Pane',
  requestId: 'research-live',
  props: { title: 'Research', isFocused: false, bodyColumns: 60, placement: 'dock' },
} as const

describe('research-live pane', () => {
  test('shows the main thread idle, then running once a turn starts', async ($, on) => {
    on('turn.start', (_$, e) => ({ turnId: e.turnId }))
    const ui = await $.ui.mount({ plugin: 'research-live', surface: 'vscode', ...PANE })
    expect(await ui.find({ type: 'Text', text: /Main thread idle/ })).toBeDefined()
    await ui.unmount()
    await $.turn.start({ text: 'go', turnId: 't1' })
    const live = await $.ui.mount({ plugin: 'research-live', surface: 'vscode', ...PANE })
    expect(await live.find({ type: 'Text', text: /Main thread running/ })).toBeDefined()
    await live.unmount()
  })

  test('says so when there is no run yet', async $ => {
    const ui = await $.ui.mount({ plugin: 'research-live', surface: 'vscode', ...PANE })
    expect(await ui.find({ type: 'Text', text: /No run folder yet/ })).toBeDefined()
    await ui.unmount()
  })
})
