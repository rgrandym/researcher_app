import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import clsx from "clsx";
import { useUi, type View } from "../stores/ui";

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

/** Where a link to a workspace file opens in the app, or null for a web link. A path the
 * agent writes (`outputs/<run>/critique.md`, an absolute path, `file.md:12`, `#L12`) would
 * otherwise open a blank page on the app's own server. */
export function fileView(href: string | undefined, run?: string): View | null {
  if (!href || href.startsWith("#")) return null;
  const local = href.replace(/^file:\/\//i, "");
  if (/^[a-z][a-z0-9+.-]*:/i.test(local) || local.startsWith("//")) return null;
  let path = local;
  try {
    path = decodeURIComponent(local);
  } catch {
    /* keep it as written */
  }
  path = path.replace(/[#?].*$/, "").replace(/:\d+(-\d+)?$/, "").replace(/^\.\//, "");
  const at = path.indexOf("outputs/");
  if (path.startsWith("/") && at < 0) return null;
  if (at > 0) path = path.slice(at);
  const match = /^outputs\/([^/]+)\/?(.*)$/.exec(path);
  if (match) return { kind: "run", name: match[1], file: match[2] || undefined };
  // inside a run's document, a bare relative path is a file of that run
  if (run && !path.startsWith("/") && !path.startsWith(".claude/")) return { kind: "run", name: run, file: path.replace(/^\.\//, "") };
  return { kind: "workspace", path };
}

export default function Markdown({ text, className, run }: { text: string; className?: string; run?: string }) {
  const { setView } = useUi();
  return (
    <div className={clsx("prose-doc", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 id={slug(textOf(children))}>{children}</h1>,
          h2: ({ children }) => <h2 id={slug(textOf(children))}>{children}</h2>,
          h3: ({ children }) => <h3 id={slug(textOf(children))}>{children}</h3>,
          a: ({ href, children }) => {
            const view = fileView(href, run);
            return (
              <a
                href={href}
                target={view ? undefined : "_blank"}
                rel="noreferrer"
                onClick={(event) => {
                  if (!view) return;
                  event.preventDefault();
                  setView(view);
                }}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
