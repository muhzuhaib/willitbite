"""B006: is a mutable default argument ever actually mutated?

A mutable default is evaluated once, at definition time, and shared by every
call that omits the argument. That is only a bug when the function changes it,
because the change is then visible to the next caller. A default that is only
read behaves exactly like the immutable one the author probably imagined.

So the decisive question is mutation, and there is one trap in asking it. A
great many functions open with ``items = items or []`` or ``items = list(items)``,
which rebinds the name to a fresh object before anything is appended. The shared
default is never touched. Mutation that happens after a rebind is mutation of
the new object, so position matters and a plain "does the name appear on the
left of an append" is not enough.
"""

import ast

from .callsites import reach
from .verdict import BITES, CALLEE, LATENT, SAFE, Verdict

#: Methods that change the receiver in place.
MUTATORS = frozenset(
    {
        "append",
        "appendleft",
        "extend",
        "extendleft",
        "insert",
        "add",
        "update",
        "difference_update",
        "intersection_update",
        "symmetric_difference_update",
        "setdefault",
        "pop",
        "popleft",
        "popitem",
        "remove",
        "clear",
        "sort",
        "reverse",
        "rotate",
        "discard",
    }
)

#: Calls that cannot change what they are given: they either only read it, or
#: they build a new object from it. Passing the default to one of these is not
#: an escape, so they must be excluded or every read looks like a risk.
NON_MUTATING = frozenset(
    {
        # build a copy
        "list", "dict", "set", "tuple", "frozenset", "copy", "deepcopy", "sorted",
        # read only
        "len", "any", "all", "sum", "min", "max", "enumerate", "iter", "reversed",
        "bool", "str", "repr", "print", "isinstance", "join", "format", "next",
    }
)

#: Factories that produce a mutable object, so ``x=dict()`` is as shared as ``x={}``.
MUTABLE_FACTORIES = frozenset(
    {"list", "dict", "set", "defaultdict", "Counter", "OrderedDict", "deque"}
)


def mutable_defaults(fn):
    """Parameter names whose default is a mutable object.

    Ruff reports the offending default's position, but recovering the parameter
    name from that is fiddlier than reading the signature directly, and the
    signature is what a reader checks the verdict against.
    """
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []

    args = fn.args
    names = []

    positional = args.posonlyargs + args.args
    if args.defaults:
        paired = zip(positional[len(positional) - len(args.defaults) :], args.defaults)
        for arg, default in paired:
            if _is_mutable(default):
                names.append(arg.arg)

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None and _is_mutable(default):
            names.append(arg.arg)

    return names


def _is_mutable(node):
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        return name in MUTABLE_FACTORIES
    return False


def _stores(target, name):
    """Does assigning to ``target`` bind the plain name ``name``?"""
    return any(
        isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store)
        for n in ast.walk(target)
    )


def _always_rebinds(body, name):
    """Line of the first statement in ``body`` that rebinds ``name`` whichever path runs.

    Only statements that cannot be skipped count: a plain assignment, a ``with``
    whose body does it, or an ``if`` whose every branch does it. A rebind inside
    ``if copy:`` leaves the name pointing at the shared default whenever the
    branch is not taken, so it protects nothing after the ``if``.
    """
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(_stores(t, name) for t in stmt.targets):
            return stmt.lineno
        if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if _stores(stmt.target, name):
                return stmt.lineno
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            if any(i.optional_vars is not None and _stores(i.optional_vars, name) for i in stmt.items):
                return stmt.lineno
            inner = _always_rebinds(stmt.body, name)
            if inner is not None:
                return inner
        if isinstance(stmt, ast.If) and stmt.orelse:
            if _always_rebinds(stmt.body, name) and _always_rebinds(stmt.orelse, name):
                return stmt.lineno
    return None


def _rebind_line(fn, name):
    """First line where ``name`` is assigned on every path, or None.

    After a rebind the name refers to a new object, so anything done to it from
    that point on cannot reach the shared default. ``items += [1]`` is not a
    rebind: on a list it calls __iadd__, which extends in place, and it is not
    an assignment statement here, so it never hides the mutation it performs.
    """
    return _always_rebinds(fn.body, name)


def _mutations(fn, name):
    """Every in-place change to ``name``, as (line, description)."""
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id == name:
                if node.func.attr in MUTATORS:
                    found.append((node.lineno, f"{name}.{node.func.attr}()"))
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id == name and isinstance(node.ctx, (ast.Store, ast.Del)):
                verb = "assigned" if isinstance(node.ctx, ast.Store) else "deleted"
                found.append((node.lineno, f"{name}[...] {verb}"))
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                found.append((node.lineno, f"{name} += ..."))
    return found


def _kept_or_returned(fn, name):
    """How the default leaves the function without being passed to a call, or None.

    ``self.items = items``, ``alias = items`` and ``return items`` all hand the
    shared object to code this body cannot see, so a mutation elsewhere reaches
    the default just as one in this body would. The name may sit inside a
    tuple, list, set or dict on its way out.
    """
    parents = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    holders = (ast.Tuple, ast.List, ast.Set, ast.Dict, ast.Starred)
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Name) and node.id == name):
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        up = parents.get(node)
        while isinstance(up, holders):
            up = parents.get(up)
        if isinstance(up, (ast.Return, ast.Yield, ast.YieldFrom)):
            return "returned"
        if isinstance(up, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and up.value is not None:
            return "stored"
    return None


def _escapes_unchanged(fn, name):
    """Is the default handed to something that could keep or mutate it?

    A default that is only read inside the function can still be mutated a frame
    down if it is passed on by reference, or later if it is stored or returned.
    Calls that provably cannot change it are excluded, or every ``len(items)``
    would look like a risk.

    Returns a sentence fragment saying how it leaves, or None.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        callee_name = (
            callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
        )
        if callee_name in NON_MUTATING:
            continue
        passed = [a for a in node.args if isinstance(a, ast.Name) and a.id == name]
        passed += [
            kw.value for kw in node.keywords
            if isinstance(kw.value, ast.Name) and kw.value.id == name
        ]
        if passed:
            return (
                f"is passed to {callee_name or 'a call'}(), which could mutate it "
                f"a frame down"
            )
    how = _kept_or_returned(fn, name)
    if how == "returned":
        return "is returned, so the caller can mutate the shared default"
    if how == "stored":
        return "is stored (on self or under another name), so it can be mutated later"
    return None


def _reaching_mutations(fn, name):
    """The mutations that touch the shared default, and the rebind line if any."""
    rebound = _rebind_line(fn, name)
    mutations = _mutations(fn, name)
    return [m for m in mutations if rebound is None or m[0] < rebound], rebound, mutations


def _defect_clause(name, reaching):
    """The half of the reason that describes the defect itself.

    Shared by BITES and LATENT so the two answers never drift into describing
    the same defect differently. Only what follows this clause changes.
    """
    where = ", ".join(f"{what} on line {line}" for line, what in sorted(reaching))
    return f"`{name}` is mutated before it is rebound ({where})"


def analyse_param(fn, name):
    """Decide one parameter of one function, from its body alone."""
    reaching, rebound, mutations = _reaching_mutations(fn, name)

    if reaching:
        return Verdict(
            BITES,
            f"{_defect_clause(name, reaching)}, so every call that omits it sees "
            f"the previous call's changes",
        )

    if rebound is not None:
        detail = " before any mutation" if mutations else ""
        return Verdict(
            SAFE,
            f"`{name}` is rebound on line {rebound}{detail}, so the shared default "
            f"is never touched",
        )

    escapee = _escapes_unchanged(fn, name)
    if escapee:
        return Verdict(
            CALLEE,
            f"`{name}` is never mutated here but {escapee}",
        )

    return Verdict(SAFE, f"`{name}` is never mutated, so sharing it is harmless")


def _owner(tree, fn):
    """The name of the class whose body defines ``fn``, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and fn in node.body:
            return node.name
    return None


def _with_call_sites(fn, name, verdict, calls, owner=None):
    """Ask the callers whether the defect in ``fn`` can currently fire.

    Only a complete answer changes anything. If every call site was resolved and
    every one of them passes the argument, the shared default is never the
    object being mutated and the defect is waiting rather than happening. Any
    other shape leaves the verdict alone: an unresolved splat, a caller that
    omits it, or no caller at all are each a reason to keep looking, not a
    reason to clear it.
    """
    if calls is None:
        return verdict

    found = reach(fn, name, calls, owner)
    reaching, _, _ = _reaching_mutations(fn, name)
    clause = _defect_clause(name, reaching)

    if found.total == 0:
        return Verdict(
            BITES,
            f"{clause}, and no call site of `{fn.name}()` was found under this path, "
            f"so nothing here shows that callers pass it",
        )
    if found.unreachable:
        plural = "" if found.total == 1 else "s"
        return Verdict(
            LATENT,
            f"{clause}, but all {found.total} call site{plural} of `{fn.name}()` pass "
            f"it explicitly, so the shared default is never the one being changed",
        )
    return verdict


def analyse(tree, line, parents=None, calls=None):
    """Decide one B006 warning reported at ``line``.

    ``calls`` is the optional call index from :mod:`willitbite.callsites`.
    Without it the answer is about the function; with it the answer is about
    the program, which is a strictly narrower and more useful claim.
    """
    from .escape import innermost_closure

    fn = innermost_closure(tree, line)
    if fn is None or isinstance(fn, ast.Lambda):
        return Verdict(CALLEE, "no function definition found at this line")

    names = mutable_defaults(fn)
    if not names:
        return Verdict(CALLEE, f"no mutable default found in the signature of `{fn.name}`")

    decided = [(n, analyse_param(fn, n)) for n in names]
    for name, verdict in decided:
        if verdict.kind == BITES:
            return _with_call_sites(fn, name, verdict, calls, _owner(tree, fn))
    for _, verdict in decided:
        if verdict.kind == CALLEE:
            return verdict
    return decided[0][1]
