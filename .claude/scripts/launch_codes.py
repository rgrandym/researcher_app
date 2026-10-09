#!/usr/bin/env python3
"""launch_codes.py: the launch-codes rules for agents that cannot run the mod.

    launch_codes.py test "<command>"     # would this command need launch codes?
    launch_codes.py codex-hook            # Codex PreToolUse hook: reads the event on stdin

Under Claude Code the launch-codes mod (launch-codes@claude-code-mods) stops risky
shell commands and asks for a one-time code from its RED ALERT pane. Codex has no mods
and no way to ask, so this hook applies the same rules and refuses the command
outright: the agent is told to stop and ask, and the author runs the command
themselves if they want it.

`classify` is a line-for-line port of the mod's hooks/classify.ts (OneWave-AI,
MIT), checked against the mod's own test cases in app/tests/test_launch_codes.py.
Keep the two in step when the mod changes.

A hook that fails refuses the command when it can tell the command is risky, and
prints nothing otherwise. Codex treats any other hook failure as "carry on".
"""
import json
import re
import sys

WRAPPERS = {"sudo", "time", "command", "exec", "nohup", "env", "npx", "bunx", "xargs", "doas"}
SAFE_RM = re.compile(r"(^|/)(node_modules|\.next|dist|tmp|\.turbo|\.cache|coverage|__pycache__)(/|$)")
SAFE_RM_ROOT = re.compile(r"^(/tmp/|/private/tmp/|\$TMPDIR|/var/folders/)")
SQL_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "duckdb", "clickhouse-client", "pgcli", "mycli"}
SQL_DROP = re.compile(r"\b(drop\s+(table|database|schema)|truncate\s+(table\s+)?[\"`\w])", re.I)
SHELLS = {"sh", "bash", "zsh", "dash", "fish"}
FETCHERS = {"curl", "wget"}


def tokenize(line):
    """Words and operators, honouring quotes and backslashes: ('w', text) or ('op', text)."""
    out, word, has_word, i = [], "", False, 0

    def flush():
        nonlocal word, has_word
        if has_word:
            out.append(("w", word))
        word, has_word = "", False

    while i < len(line):
        c = line[i]
        if c == "'":
            end = line.find("'", i + 1)
            word += line[i + 1:len(line) if end == -1 else end]
            has_word = True
            i = len(line) if end == -1 else end
        elif c == '"':
            j = i + 1
            while j < len(line) and line[j] != '"':
                if line[j] == "\\" and j + 1 < len(line):
                    j += 1
                word += line[j]
                j += 1
            has_word = True
            i = j
        elif c == "\\" and i + 1 < len(line):
            word += line[i + 1]
            has_word = True
            i += 1
        elif c in " \t":
            flush()
        elif c in "\n;":
            flush()
            out.append(("op", ";"))
        elif c in "&|":
            flush()
            pair = i + 1 < len(line) and line[i + 1] == c
            out.append(("op", c + c if pair else c))
            if pair:
                i += 1
        elif c in "()":
            flush()
            out.append(("op", c))
        else:
            word += c
            has_word = True
        i += 1
    flush()
    return out


def program(words):
    """The program a command really runs, past sudo, env assignments and npx."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) or w in WRAPPERS or (w.startswith("-") and i > 0):
            i += 1
            continue
        if w in ("pnpm", "yarn", "bun") and i + 1 < len(words) and words[i + 1] == "dlx":
            i += 2
            continue
        break
    name = words[i].split("/")[-1] if i < len(words) else ""
    return name, words[i + 1:]


def simples(tokens):
    """Simple commands, each with the program piped into it (or None)."""
    out, words, piped_from = [], [], None

    def end(op):
        nonlocal words, piped_from
        if words:
            name = program(words)[0]
            out.append((words, piped_from))
            piped_from = name if op == "|" else None
        elif op != "|":
            piped_from = None
        words = []

    for kind, text in tokens:
        if kind == "op":
            end(text)
        else:
            words.append(text)
    end(";")
    return out


def rm_danger(args):
    recursive = force = end_of_flags = False
    targets = []
    for a in args:
        if not end_of_flags and a == "--":
            end_of_flags = True
        elif not end_of_flags and a.startswith("--"):
            recursive = recursive or a == "--recursive"
            force = force or a == "--force"
        elif not end_of_flags and a.startswith("-") and len(a) > 1:
            recursive = recursive or bool(re.search(r"[rR]", a))
            force = force or "f" in a
        else:
            targets.append(a)
    if not (recursive and force and targets):
        return None
    risky = [t for t in targets if not (SAFE_RM.search(t) or SAFE_RM_ROOT.search(t))]
    return ("rm", f"rm -rf on {' '.join(risky[:3])}") if risky else None


def classify(command):
    """(kind, reason) for the first dangerous thing `command` does, or None."""
    for words, piped_from in simples(tokenize(command)):
        name, args = program(words)
        joined = " ".join(args)

        if name == "rm":
            d = rm_danger(args)
            if d:
                return d

        if name == "git":
            at = 0  # git's own options come before the subcommand; -C and -c take a value
            while at < len(args) and args[at].startswith("-"):
                at += 2 if args[at] in ("-C", "-c", "--git-dir", "--work-tree") else 1
            sub = args[at] if at < len(args) else None
            if sub == "push":
                rest = args[at + 1:]
                if any(a == "--force" or re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", a) or re.match(r"^\+\S", a) for a in rest):
                    return ("git-push-force", "git push --force rewrites remote history")
            if sub == "reset" and "--hard" in args:
                return ("git-reset-hard", "git reset --hard throws away uncommitted work")

        # A heredoc's body lands in commands of its own, so then the whole line counts.
        sql = command if any(a.startswith("<<") for a in args) else joined
        if name in SQL_CLIENTS and SQL_DROP.search(sql):
            return ("sql-drop", "DROP / TRUNCATE through a live SQL client")

        if name == "supabase":
            if args[:2] == ["db", "reset"]:
                return ("supabase-reset", "supabase db reset wipes the database")
            if SQL_DROP.search(joined):
                return ("sql-drop", "DROP / TRUNCATE through supabase")

        if name == "vercel" and any(a in ("--prod", "--production") for a in args):
            return ("vercel-prod", "vercel --prod ships to production")

        if (name == "chmod" and any(re.match(r"^-[a-zA-Z]*R", a) or a == "--recursive" for a in args)
                and any(re.match(r"^0?777$", a) or a == "a+rwx" for a in args)):
            return ("chmod-777", "chmod -R 777 opens every file to everyone")

        if name in SHELLS and piped_from in FETCHERS:
            return ("curl-sh", f"{piped_from} piped straight into {name}")
        if name in SHELLS and any(re.search(r"\$\(\s*(curl|wget)\b", a) for a in args):
            return ("curl-sh", f"{name} running a downloaded script")
    # bash <(curl ...): the tokenizer splits the parens off, so look at the raw line.
    if re.search(r"\b(sh|bash|zsh)\s+<\(\s*(curl|wget)\b", command):
        return ("curl-sh", "shell running a downloaded script")
    return None


# ---------------------------------------------------------------- the Codex hook

def command_of(event):
    """The shell command a Codex tool call runs, or None for anything else."""
    if event.get("tool_name") == "apply_patch":
        return None
    raw = event.get("tool_input")
    tool_input = raw if isinstance(raw, dict) else {"command": raw}
    cmd = tool_input.get("command") or tool_input.get("cmd")
    if isinstance(cmd, list):
        words = [str(w) for w in cmd]
        # ["bash", "-lc", "<script>"]: the script is what runs.
        if len(words) >= 3 and words[1] in ("-c", "-lc", "-ic"):
            return words[2]
        return " ".join(words)
    if isinstance(cmd, str) and not cmd.lstrip().startswith("*** Begin Patch"):
        return cmd
    return None


def deny(text):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": text,
    }}))


def codex_hook(event):
    command = command_of(event)
    if not command:
        return
    try:
        danger = classify(command)
    except Exception:                                      # noqa: BLE001  fail closed on a risky-looking line
        if re.search(r"\b(rm|push|reset|drop|truncate|chmod|vercel|supabase)\b", command, re.I):
            deny("launch-codes: the launch check failed on this command; ask the author before retrying.")
        return
    if danger:
        short = command if len(command) <= 120 else command[:117] + "..."
        deny(f"launch-codes: blocked `{short}` ({danger[1]}). Codex cannot ask for launch codes, so this "
             "command never runs from an agent. Do not retry it or work around the check; tell the author "
             "what you wanted to run and why, so they can run it themselves, or find a safer way.")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "codex-hook":
        try:
            codex_hook(json.loads(sys.stdin.read() or "{}"))
        except ValueError:
            pass
        return 0
    if cmd == "test" and len(argv) > 2:
        danger = classify(" ".join(argv[2:]))
        print(f"Needs launch codes: {danger[1]}." if danger else "Safe: runs without launch codes.")
        return 1 if danger else 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
