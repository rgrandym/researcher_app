export type Step = { label: string; done: boolean }

export type RunStatus = {
  name: string
  round: string | null
  steps: Step[]
  notes: number
  evidence: number
}

export type Status = {
  run: RunStatus | null
  pending_edit: { run: string; file: string; mtime: number } | null
  stale_exports: { run: string; style: string; mtime: number }[]
  at: number
}

export type AgentRow = {
  id: string
  type: string
  description: string
  status: 'running' | 'done' | 'failed'
  started: number
  ended: number | null
}

export type MainRow = {
  isRunning: boolean
  started: number | null
  calls: number
  last: string
}

declare module 'claude-code' {
  interface PluginState {
    'research-live': {
      status: Status | null
      agents: AgentRow[]
      main: MainRow
      frame: number
      since: number
      handled: Record<string, number>
      note: string
    }
  }
}
