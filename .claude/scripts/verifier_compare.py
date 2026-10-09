#!/usr/bin/env python3
"""verifier_compare.py — does a cheaper model verify as well as the one we use?

    verifier_compare.py sample <run> [--n 15] [--seed 1]         # pick claims, write the batch
    verifier_compare.py run    <run> --model sonnet [--only C4,C9] # verify the batch headless
    verifier_compare.py score  <run> --model sonnet                # agreement with the ledger

The run's `verification.md` holds per-claim verdicts from the model the workspace
uses now. `sample` takes every non-SUPPORTED claim (the defects a verifier exists to
catch) and fills the rest with SUPPORTED ones, and writes the batch to
`<run>/notes/compare/batch.md`. `run` sends that batch to the `source-verifier`
agent on the named model, headless, and stores its raw output beside the batch.
`score` parses both and reports agreement, overall and on the verdicts that change a
report (anything but SUPPORTED).

A disagreement is not yet a verdict on the model: the ledger may be months old and
the page may have changed. Re-run only the disagreements on the current model
(`run --model opus --only …`) and score that too; where today's two models agree with
each other and not with the ledger, the page moved.

The switch rule: move the verifier to the
cheaper model only if it catches the defects the current one catches.
"""
import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEAD = re.compile(r"^#{2,3} (C\d+)\b[^\n]*", re.M)
VERDICT = re.compile(r"\*\*Verdict:\*\*\s*([A-Z][A-Z-]+)")
DRAFT = re.compile(r"\*\*Draft says:\*\*\s*(.+)")
EIDS = re.compile(r"\[(E\d+)\]")
LINE = re.compile(r"^(C\d+)\s*\|\s*([A-Z][A-Z-]+)", re.M)
DEFECTS = {"PARTIAL", "WEAK", "CIRCULAR", "UNSUPPORTED", "CONTRADICTED", "FABRICATED", "STALE"}


def ledger(run):
    text = (Path(run) / "verification.md").read_text()
    heads = list(HEAD.finditer(text))
    out = {}
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        v, d = VERDICT.search(body), DRAFT.search(body)
        if v and d:
            out[h.group(1)] = {"verdict": v.group(1), "draft": d.group(1).strip(),
                               "eids": sorted(set(EIDS.findall(body)))}
    return out


def folder(run):
    path = Path(run) / "notes" / "compare"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sample(run, n, seed):
    claims = ledger(run)
    defects = [c for c, r in claims.items() if r["verdict"] in DEFECTS]
    clean = [c for c, r in claims.items() if r["verdict"] == "SUPPORTED"]
    random.Random(seed).shuffle(clean)
    chosen = sorted(defects + clean[: max(0, n - len(defects))], key=lambda c: int(c[1:]))
    lines = [f"RUN DIR: {run}", "", "Verify each claim below against its cited evidence rows.", ""]
    for c in chosen:
        r = claims[c]
        lines.append(f"{c} | draft: {r['draft']} | cited: {' '.join(r['eids']) or '(none)'}")
    (folder(run) / "batch.md").write_text("\n".join(lines) + "\n")
    (folder(run) / "expected.json").write_text(json.dumps({c: claims[c]["verdict"] for c in chosen}, indent=1))
    kinds = {}
    for c in chosen:
        kinds[claims[c]["verdict"]] = kinds.get(claims[c]["verdict"], 0) + 1
    print(f"{len(chosen)} claims: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"batch: {folder(run) / 'batch.md'}")
    return 0


def run_model(run, model, only):
    batch = (folder(run) / "batch.md").read_text()
    if only:
        keep = set(only.split(","))
        batch = "\n".join(ln for ln in batch.splitlines()
                          if not re.match(r"C\d+ \|", ln) or ln.split(" |")[0] in keep)
    out = folder(run) / f"result-{model}{'-only' if only else ''}.txt"
    proc = subprocess.run(
        ["claude", "-p", batch, "--agent", "source-verifier", "--model", model,
         "--output-format", "json", "--permission-mode", "default",
         "--allowedTools", "Read,Grep,Bash,WebFetch,WebSearch"],
        cwd=ROOT, capture_output=True, text=True, timeout=3600)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        print(proc.stdout[-2000:] or proc.stderr[-2000:], file=sys.stderr)
        return 1
    out.write_text(data.get("result", ""))
    print(f"{model}: cost ${data.get('total_cost_usd', 0):.2f}, {data.get('num_turns')} turns -> {out}")
    return 0


def score(run, model):
    expected = json.loads((folder(run) / "expected.json").read_text())
    got = {}
    for name in (f"result-{model}.txt", f"result-{model}-only.txt"):
        path = folder(run) / name
        if path.exists():
            got.update(dict(LINE.findall(path.read_text())))
    both = [c for c in expected if c in got]
    agree = [c for c in both if got[c] == expected[c]]
    flagged = [c for c in both if expected[c] in DEFECTS]
    caught = [c for c in flagged if got[c] in DEFECTS]
    false_alarm = [c for c in both if expected[c] == "SUPPORTED" and got[c] in DEFECTS]
    print(f"{model}: {len(both)} of {len(expected)} claims returned")
    print(f"  exact agreement      {len(agree)}/{len(both)}")
    print(f"  defects caught       {len(caught)}/{len(flagged)} (ledger said not SUPPORTED)")
    print(f"  new defects raised   {len(false_alarm)} (ledger said SUPPORTED)")
    for c in both:
        if got[c] != expected[c]:
            print(f"  {c}: ledger {expected[c]}, {model} {got[c]}")
    missing = [c for c in expected if c not in got]
    if missing:
        print(f"  not returned: {', '.join(missing)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample")
    p.add_argument("run")
    p.add_argument("--n", type=int, default=15)
    p.add_argument("--seed", type=int, default=1)
    p = sub.add_parser("run")
    p.add_argument("run")
    p.add_argument("--model", required=True)
    p.add_argument("--only")
    p = sub.add_parser("score")
    p.add_argument("run")
    p.add_argument("--model", required=True)
    a = ap.parse_args()
    if a.cmd == "sample":
        return sample(a.run, a.n, a.seed)
    if a.cmd == "run":
        return run_model(a.run, a.model, a.only)
    return score(a.run, a.model)


if __name__ == "__main__":
    sys.exit(main())
