export type Task = {
  id?: string; title?: string; project?: string; domain?: string
  status?: string; priority?: string; created?: string; body?: string; _file: string
}
export type WikiPage = { slug: string; title?: string; type?: string; status?: string; links: string[] }
export type Account = { email: string; rank?: number; connected?: boolean; role?: string }
export type Perm = { level: "always" | "ask" | "never"; _note?: string }
export type ChatTurn = { role: "user" | "nathanbot"; text: string; error?: boolean }

export type State = {
  open: Task[]; done: Task[]
  brief: string; wiki: WikiPage[]; inbox: string[]
  permissions: Record<string, Record<string, Perm>>
  accounts: Record<string, Account>
  chat: ChatTurn[]
}

export type ChatReply = { ok: boolean; reply?: string; isError?: boolean; error?: string }

async function j<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok && res.status >= 500) throw new Error(`server ${res.status}`)
  return res.json() as Promise<T>
}

export const api = {
  state: (): Promise<State> => j("/api/state"),
  say: (text: string): Promise<{ verb: string; output: string }> => j("/api/say", { text }),
  run: (cmd: string): Promise<{ output: string }> => j("/api/run", { cmd }),
  chat: (text: string): Promise<ChatReply> => j("/api/chat", { text }),
  clearChat: () => j("/api/chat/clear", {}),
  setStatus: (id: string, status: string) => j("/api/status", { id, status }),
}
