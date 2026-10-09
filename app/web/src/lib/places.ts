// Where the author was in each project: the tab, the file, the HTML style, the scroll
// position of every pane, and any unsaved text in the editor. A project view unmounts
// when the author goes to Workspace, Models or another view; this keeps its place for
// the life of the window, so coming back lands where they left.

export interface Draft {
  text: string;
  original: string;
  mtime: number | null;
}

export interface Place {
  tab?: "document" | "chat" | "html" | "edit" | "file";
  selected?: string;
  editPath?: string;
  style?: string;
  cite?: boolean;
  scroll: Record<string, number>;
  drafts: Record<string, Draft>;
}

const places = new Map<string, Place>();

export function place(run: string): Place {
  let p = places.get(run);
  if (!p) {
    p = { scroll: {}, drafts: {} };
    places.set(run, p);
  }
  return p;
}

export function remember(run: string, patch: Partial<Omit<Place, "scroll" | "drafts">>): void {
  Object.assign(place(run), patch);
}

export function rememberScroll(run: string, key: string, top: number): void {
  place(run).scroll[key] = top;
}

export function rememberDraft(run: string, path: string, draft: Draft | null): void {
  const drafts = place(run).drafts;
  if (draft && draft.text !== draft.original) drafts[path] = draft;
  else delete drafts[path];
}
