# nathanbot UI (React + Vite + shadcn/ui)

The dashboard. Real component library so it's extensible in your own stack.

- **Stack:** Vite · React · TypeScript · Tailwind v4 · shadcn/ui (radix-nova preset, Geist font)
- **API:** typed client in `src/lib/api.ts` → the Python server (`../ui/server.py`)
- **Build:** `nb build-ui` (or `npm run build`) → outputs to `../ui/dist`, which the server serves
- **Dev:** `npm run dev` (proxies /api to :7777) for hot-reload while editing

Components live in `src/components/ui/` (shadcn source — yours to edit).
Custom: `Pipeline`, `TaskRow`, `Panel`.
