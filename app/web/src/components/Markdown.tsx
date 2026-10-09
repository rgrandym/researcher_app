import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import clsx from "clsx";

export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function textOf(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(textOf).join("");
  if (children && typeof children === "object" && "props" in children) {
    return textOf((children as { props: { children?: React.ReactNode } }).props.children);
  }
  return "";
}

export default function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={clsx("prose-doc", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 id={slug(textOf(children))}>{children}</h1>,
          h2: ({ children }) => <h2 id={slug(textOf(children))}>{children}</h2>,
          h3: ({ children }) => <h3 id={slug(textOf(children))}>{children}</h3>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
