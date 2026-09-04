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

from .verdict import BITES, CALLEE, SAFE, Verdict

#: Methods that change the receiver in place.
MUTATORS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "add",
        "update",
        "setdefault",
        "pop",
        "popitem",
        "remove",
        "clear",
        "sort",
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


def _rebind_line(fn, name):
    """First line where ``name`` is assigned, or None.

    After a rebind the name refers to a new object, so anything done to it from
    that point on cannot reach the shared default.
    """
    augmented = {
        node.target
        for node in ast.walk(fn)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
    }
    lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Store)
        # ``items += [1]`` on a list calls __iadd__, which extends in place. It
        # is a Store node but it does not produce a new object, so counting it
        # as a rebind would hide the very mutation it performs.
        and node not in augmented
    ]
    return min(lines) if lines else None


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


def _escapes_unchanged(fn, name):
    """Is the default handed to something that could keep or mutate it?

    A default that is only read inside the function can still be mutated a frame
    down if it is passed on by reference. Calls that provably cannot change it
    are excluded, or every ``len(items)`` would look like a risk.
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
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == name:
                return callee_name or "a call"
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name) and kw.value.id == name:
                return callee_name or "a call"
    return None


def analyse_param(fn, name):
    """Decide one parameter of one function."""
    rebound = _rebind_line(fn, name)
    mutations = _mutations(fn, name)
    reaching = [m for m in mutations if rebound is None or m[0] < rebound]

    if reaching:
        where = ", ".join(f"{what} on line {line}" for line, what in sorted(reaching))
        return Verdict(
            BITES,
            f"`{name}` is mutated before it is rebound ({where}), so every call "
            f"that omits it sees the previous call's changes",
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
            f"`{name}` is never mutated here but is passed to {escapee}(), which "
            f"could mutate it a frame down",
        )

    return Verdict(SAFE, f"`{name}` is never mutated, so sharing it is harmless")


def analyse(tree, line, parents=None):
    """Decide one B006 warning reported at ``line``."""
    from .escape import innermost_closure

    fn = innermost_closure(tree, line)
    if fn is None or isinstance(fn, ast.Lambda):
        return Verdict(CALLEE, "no function definition found at this line")

    names = mutable_defaults(fn)
    if not names:
        return Verdict(CALLEE, f"no mutable default found in the signature of `{fn.name}`")

    decided = [(n, analyse_param(fn, n)) for n in names]
    for _, verdict in decided:
        if verdict.kind == BITES:
            return verdict
    for _, verdict in decided:
        if verdict.kind == CALLEE:
            return verdict
    return decided[0][1]
