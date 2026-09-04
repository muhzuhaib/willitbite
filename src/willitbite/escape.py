"""B023: does a closure that captures a loop variable outlive its iteration?

Ruff flags every closure inside a loop that reads the loop variable. That is a
description of a shape, not of a bug. The bug is late binding: if the closure is
still callable after the loop moves on, every copy of it sees the loop
variable's final value. If the closure is built and consumed inside the same
iteration, it sees the value it was written next to.

So the question here is never "does it capture". Ruff answered that. It is
"can this closure still be called once the loop variable has changed".

For a nested ``def NAME``, the evidence is what the loop body does with NAME:

    every reference is ``NAME(...)``          -> SAFE, it runs in its own iteration
    a bare reference that is stored           -> BITES
    a bare reference passed to ``f(NAME)``    -> CALLEE, depends on f

For a ``lambda``, the evidence is the construct that owns it: an argument to
``sorted`` runs now; ``.append`` and ``functools.partial`` keep it for later.
"""

import ast

from .verdict import BITES, CALLEE, SAFE, Verdict

LOOPS = (ast.For, ast.AsyncFor, ast.While)

#: Builtins that call the closure and drop it before the expression finishes.
CONSUMING = frozenset(
    {"sorted", "min", "max", "sum", "any", "all", "sort", "nlargest", "nsmallest"}
)

#: Builtins that return a lazy iterator holding the closure. Safe only if the
#: result is consumed in the same iteration, which is a separate question.
LAZY = frozenset({"map", "filter", "groupby"})

#: Attribute calls whose whole purpose is to keep the callable for later.
KEEPING_ATTRS = frozenset(
    {
        "append",
        "add",
        "insert",
        "extend",
        "submit",
        "apply_async",
        "put",
        "add_done_callback",
        "connect",
        "register",
        "subscribe",
        "schedule",
        "create_task",
        "run_in_executor",
        "call_later",
        "call_soon",
        "setdefault",
    }
)

#: Constructors and helpers that store the callable in the object they return.
KEEPING_CALLS = frozenset(
    {"partial", "Thread", "Timer", "Process", "create_task", "ensure_future"}
)


def parent_map(tree):
    """Map every node to its parent. ast exposes children only."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def innermost_closure(tree, line):
    """The lambda or def enclosing ``line``, innermost when several do.

    Ruff points at the captured name, not at the closure, so the closure has to
    be found by span. The one that starts latest is the innermost.
    """
    holding = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.lineno <= line <= getattr(n, "end_lineno", n.lineno)
    ]
    return max(holding, key=lambda n: n.lineno) if holding else None


def enclosing_loop(node, parents):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, LOOPS):
            return cur
    return None


def _callee_name(call):
    fn = call.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def classify_def(fn, loop, parents):
    """A nested def: what does the loop body do with its name?"""
    if loop is None:
        return Verdict(CALLEE, f"`{fn.name}` is not inside a loop in this file")

    name = fn.name
    called = 0
    stored = []
    passed = []
    for node in ast.walk(loop):
        if not isinstance(node, ast.Name) or node.id != name:
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        up = parents.get(node)
        if isinstance(up, ast.Call) and up.func is node:
            called += 1
        elif isinstance(up, ast.Call):
            passed.append(_callee_name(up) or "a call")
        else:
            stored.append(type(up).__name__)

    if stored:
        where = ", ".join(sorted(set(stored)))
        return Verdict(
            BITES,
            f"`{name}` is stored rather than called ({where}), so it can run "
            f"after the loop variable has changed",
        )
    keepers = sorted({p for p in passed if p in KEEPING_ATTRS or p in KEEPING_CALLS})
    if keepers:
        who = ", ".join(keepers)
        return Verdict(
            BITES,
            f"`{name}` is stored rather than called: it is handed to {who}(), "
            f"which keeps it past the end of the iteration",
        )
    if passed:
        runners = {p for p in passed if p in CONSUMING}
        rest = sorted(set(passed) - runners)
        if not rest:
            who = ", ".join(sorted(runners))
            return Verdict(
                SAFE, f"`{name}` is only ever an argument to {who}(), which runs it now"
            )
        who = ", ".join(rest)
        return Verdict(
            CALLEE,
            f"`{name}` is handed to {who}(), so it bites only if {who} keeps it "
            f"instead of calling it",
        )
    if called:
        return Verdict(
            SAFE,
            f"`{name}` is only ever called directly, {called} time(s) in the "
            f"same iteration",
        )
    return Verdict(
        BITES,
        f"`{name}` is never used inside the loop, so whatever holds it outlives "
        f"the iteration",
    )


def classify_lambda(node, parents):
    """A lambda: which construct owns it?"""
    cur = node
    while cur in parents:
        up = parents[cur]
        if isinstance(up, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            return Verdict(BITES, "the lambda is bound to a name, so it is called later")
        if isinstance(up, (ast.Dict, ast.List, ast.Set, ast.Tuple)):
            return Verdict(BITES, "the lambda is stored in a container")
        if isinstance(up, ast.Return):
            return Verdict(BITES, "the lambda is returned out of the function")
        if isinstance(up, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return Verdict(BITES, "the lambda is collected by a comprehension")
        if isinstance(up, ast.Call):
            name = _callee_name(up)
            if name in KEEPING_ATTRS or name in KEEPING_CALLS:
                return Verdict(BITES, f"the lambda is handed to {name}(), which keeps it")
            if name in CONSUMING:
                return Verdict(
                    SAFE, f"the lambda is an argument to {name}(), which runs it now"
                )
            if name in LAZY:
                return Verdict(
                    CALLEE,
                    f"the lambda is an argument to {name}(), which is lazy, so it is "
                    f"safe only if the result is consumed in this iteration",
                )
            return Verdict(
                CALLEE,
                f"the lambda is handed to {name}(), so it bites only if {name} keeps it",
            )
        cur = up
    return Verdict(CALLEE, "the owning construct could not be identified")


def analyse(tree, line, parents=None):
    """Decide one B023 warning reported at ``line``."""
    parents = parent_map(tree) if parents is None else parents
    closure = innermost_closure(tree, line)
    if closure is None:
        return Verdict(CALLEE, "no closure found at this line")
    if isinstance(closure, ast.Lambda):
        return classify_lambda(closure, parents)
    return classify_def(closure, enclosing_loop(closure, parents), parents)
