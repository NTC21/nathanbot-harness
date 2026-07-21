import { memo } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

// Prose styling for assistant replies — clean sans, no bubble. Matches Claude/GPT.
const components: Components = {
  h1: ({ node, ...p }) => <h1 className="mt-5 mb-2 text-lg font-semibold first:mt-0" {...p} />,
  h2: ({ node, ...p }) => <h2 className="mt-5 mb-2 text-base font-semibold first:mt-0" {...p} />,
  h3: ({ node, ...p }) => <h3 className="mt-4 mb-1.5 text-[15px] font-semibold first:mt-0" {...p} />,
  p: ({ node, ...p }) => <p className="my-2.5 leading-relaxed first:mt-0 last:mb-0" {...p} />,
  a: ({ node, ...p }) => <a className="text-foreground underline underline-offset-2 hover:opacity-80" target="_blank" rel="noreferrer" {...p} />,
  ul: ({ node, ...p }) => <ul className="my-2.5 flex list-disc flex-col gap-1 pl-5" {...p} />,
  ol: ({ node, ...p }) => <ol className="my-2.5 flex list-decimal flex-col gap-1 pl-5" {...p} />,
  li: ({ node, ...p }) => <li className="leading-relaxed" {...p} />,
  strong: ({ node, ...p }) => <strong className="font-semibold" {...p} />,
  blockquote: ({ node, ...p }) => <blockquote className="my-3 border-l-2 border-border pl-3 text-muted-foreground" {...p} />,
  hr: () => <hr className="my-4 border-border" />,
  code: ({ node, className, children, ...p }) => {
    const inline = !className
    return inline
      ? <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.85em]" {...p}>{children}</code>
      : <code className={className} {...p}>{children}</code>
  },
  pre: ({ node, ...p }) => <pre className="my-3 overflow-x-auto rounded-lg bg-muted p-3 font-mono text-[13px] leading-relaxed" {...p} />,
  table: ({ node, ...p }) => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-[13px]" {...p} /></div>,
  th: ({ node, ...p }) => <th className="border border-border px-2.5 py-1.5 text-left font-medium" {...p} />,
  td: ({ node, ...p }) => <td className="border border-border px-2.5 py-1.5" {...p} />,
}

export const MarkdownText = memo(function MarkdownText({ text }: { text: string }) {
  return (
    <div className="text-[15px] text-foreground wrap-break-word">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>
    </div>
  )
})
