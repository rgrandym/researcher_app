export type Web = { searches: number; fetches: number; extraSearches: number; extraFetches: number; warned: number }
export type AgentTally = { tokensIn: number; tokensOut: number; web: number }
export type AgentRow = { id: string; type: string; description: string; status: string }
export type Stage = { status: string; name: string; detail: string }
export type Conf = { searchCap: number; fetchCap: number; warnEvery: number; raise: { searches: number; fetches: number }; isLoaded: boolean }
export type Usage = { usd?: number; contextPercent?: number; windows: { kind: string; percentUsed: number; resetsAt?: string }[] }

declare module 'claude-code' {
  interface PluginState {
    'research-monitor': {
      web: Web
      tallies: Record<string, AgentTally>
      agents: AgentRow[]
      run: string | null
      stages: Stage[]
      usage: Usage
      conf: Conf
    }
  }
}
