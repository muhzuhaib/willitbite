"""Who calls this, and do any of them leave the argument out?

A function that mutates its own mutable default is wrong. That is a property of
the function and it does not depend on anybody else. Whether the wrongness can
reach you is a property of the program, and it turns on one thing: some caller
has to omit the argument. If every call site passes an explicit value, the
shared default is never the object being mutated and the bug sits there waiting
for a caller who does not yet exist.

Both facts are worth reporting, and they are different facts. So this produces a
second verdict of its own and the first one stays visible underneath it.

**Matching is by name, and it is deliberately generous.** Resolving ``x.send()``
to a definition properly needs type inference, which this does not have. So a
call is counted whenever the called name matches, wherever it appears. That
over-matches: an unrelated ``send`` in another module is counted too. The
over-matching is in the safe direction, because an extra caller can only ever
add an omission and an omission is the answer that keeps the warning. Import
aliases are resolved (``from lib import collect as c`` files ``c(...)`` under
``collect`` too), and so are chains of them across modules: a package that
re-exports ``collect`` as ``c`` makes ``from pkg import c`` a caller of
``collect``. A re-export written as an assignment (``c = collect``) is
followed too, and so is a plain rebinding of a name to another name. All of
them matter because a second spelling hides callers without adding any, and
hidden callers are the one direction this pass must never err in.

**Everything unresolvable stays unresolved.** A ``**kwargs`` splat might be
carrying the argument, a ``*args`` splat might be filling the position, and a
function with no visible caller at all might be a public entry point that half
the internet calls. None of those is evidence of safety, so each of them leaves
the verdict where it was. The only thing that downgrades a warning here is a
complete set of call sites that every one of them supplies the argument.
"""

import ast
import os
from collections import defaultdict
from dataclasses import dataclass

#: Directories that are never the project's own source. Scanning them wastes
#: time and, worse, a vendored copy of the same function invents call sites the
#: project does not have.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "site-packages",
        "build",
        "dist",
    }
)


@dataclass(frozen=True)
class Call:
    """One call, remembered well enough to answer questions about its arguments."""

    filename: str
    line: int
    node: ast.Call
    attribute: bool  #: written as ``x.name(...)`` rather than ``name(...)``


def python_files(root):
    """Every ``.py`` file under ``root``, skipping the directories above."""
    root = str(root)
    if os.path.isfile(root):
        yield root
        return
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [d for d in subfolders if d not in SKIP_DIRS]
        for name in names:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


def module_name(filename):
    """The dotted module name of ``filename``, relative to its package root.

    Python resolves imports against package roots, not against whatever
    directory happened to be scanned, so the name is derived by walking up
    from the file only while each directory carries an ``__init__.py``. That
    makes ``src/pkg/lib.py`` name itself ``pkg.lib`` exactly as the imports
    inside the tree spell it, and a directory of loose scripts stays flat.
    """
    folder, name = os.path.split(os.path.abspath(filename))
    parts = [] if name == "__init__.py" else [name[:-3]]
    while os.path.isfile(os.path.join(folder, "__init__.py")):
        folder, head = os.path.split(folder)
        if not head:
            break
        parts.append(head)
    parts.reverse()
    return ".".join(parts)


def _source_module(module, is_package, level, target):
    """Where an import imports from, as an absolute module path.

    A relative level counts up from the package containing the file's own
    module: one dot for a package's own ``__init__`` and for its siblings.
    A level that walks past the top of the derived tree cannot be resolved
    against anything real, so the bare module is kept rather than dropped:
    the binding still names what it imports, and a name is all the first hop
    of a chain needs.
    """
    if level == 0:
        return target
    base = module.split(".") if module else []
    if not is_package:
        base = base[:-1]
    if level - 1 > len(base):
        return target
    base = base[: len(base) - (level - 1)]
    if target:
        base.append(target)
    return ".".join(base)


def import_bindings(tree, module, is_package):
    """Map each local name ``tree`` imports to where it was imported from.

    ``from lib import collect as c`` records ``c`` standing for ``collect``
    of module ``lib``, and imports without an ``as`` are recorded too,
    because a later hop through a re-export needs the edge. The values are
    sets: two imports of one local name keep both branches, and two files
    that derive the same module name in a flat tree merge rather than
    overwrite. Either way following a branch only ever adds a spelling,
    which is the safe direction.

    Bindings from inside functions are collected as if they were module
    level, which over-approximates scope. Over-matching adds callers, and
    added callers are the safe direction. Plain ``import lib`` is absent on
    purpose: its calls are attribute calls and the attribute name is already
    indexed. A star import names no local binding at all.
    """
    bindings = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _source_module(module, is_package, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            bindings.setdefault(local, set()).add((source, alias.name))
    return bindings


def rebindings(tree, module):
    """Map each local name ``tree`` binds to another name to the name it stands for.

    ``c = collect`` makes ``c`` another spelling of ``collect``, and a package
    that re-exports by assignment rather than by import (``from lib import
    collect`` in its ``__init__.py``, then ``c = collect``) is the shape that
    reaches a caller who writes ``from pkg import c``. The edge points at the
    module doing the binding rather than at the module the name originally came
    from, because the next hop resolves it there through that module's own
    imports: ``c`` in ``pkg`` reaches ``collect`` in ``pkg``, which reaches
    ``collect`` in ``lib``.

    ``c = mod.collect`` records the attribute's own name, for the same reason
    the index already files ``mod.collect(...)`` under ``collect``: the spelling
    is what the eventual match needs and where it lives is not.

    Annotated assignments count, ``a = b = collect`` binds both targets, and
    assignments inside functions are collected as if they were module level,
    exactly as the import table over-approximates scope. A value that is not a
    plain name or attribute binds no spelling worth following: a call, a literal
    or a comprehension builds a new object rather than another way to say an
    existing one. ``collect = collect`` is skipped because an edge from a name
    to itself says nothing the written spelling does not already say.
    """
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if isinstance(value, ast.Name):
            name = value.id
        elif isinstance(value, ast.Attribute):
            name = value.attr
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id != name:
                bindings.setdefault(target.id, set()).add((module, name))
    return bindings


def _parse(filename):
    """One file's syntax tree, or None if it cannot be read or parsed."""
    # Closed explicitly rather than left to the collector: this runs once
    # per file across a whole source tree, and a few thousand open handles
    # is its own kind of failure.
    try:
        with open(filename, encoding="utf-8") as handle:
            return ast.parse(handle.read())
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return None


def _spellings(module, name, bindings):
    """Every name ``name`` in ``module`` can be reached under, itself included.

    Each hop follows one import binding, so ``from pkg import c`` where
    ``pkg`` re-exports ``collect`` as ``c`` ends at ``collect``, however many
    packages the re-export passes through. A hop whose target module is not
    in the tree still contributes its name, which is all the eventual match
    needs, and then ends there. The spelling written in the source file
    always stays, because some other module may define a function of its own
    under it. The visited set is what makes a cycle of re-exports terminate.
    """
    names = {name}
    seen = {(module, name)}
    frontier = [(module, name)]
    while frontier:
        current = frontier.pop()
        for target in bindings.get(current[0], {}).get(current[1], ()):
            if target not in seen:
                seen.add(target)
                names.add(target[1])
                frontier.append(target)
    return names


def index(root):
    """Map every called name under ``root`` to the calls that use it.

    A file that cannot be read or parsed is skipped rather than fatal. The index
    is a source of evidence, and missing evidence is already handled: it leaves
    warnings where they are.

    Two passes: the bindings of every module are collected first, both the
    ones its imports make and the ones its assignments make, because a call
    can only be filed under its full chain of spellings once every module's
    bindings are known. Files are parsed again for their calls
    rather than held in memory: a tree of a few thousand files is real, and a
    few thousand live syntax trees is its own kind of failure.
    """
    bindings = defaultdict(dict)
    for filename in python_files(root):
        tree = _parse(filename)
        if tree is None:
            continue
        module = module_name(filename)
        is_package = os.path.basename(filename) == "__init__.py"
        table = bindings[module]
        for local, sources in import_bindings(tree, module, is_package).items():
            table.setdefault(local, set()).update(sources)
        # Assignments go into the same table as imports because a hop does not
        # care which of the two made the edge, only where the name goes next.
        for local, sources in rebindings(tree, module).items():
            table.setdefault(local, set()).update(sources)

    found = defaultdict(list)
    for filename in python_files(root):
        tree = _parse(filename)
        if tree is None:
            continue
        module = module_name(filename)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name):
                call = Call(filename, node.lineno, node, False)
                # Under every spelling the name can be reached under, so the
                # definition sees its callers through aliases and re-exports
                # alike. Purely additive: the written spelling stays indexed
                # for any same-named function of its own.
                for spelling in _spellings(module, callee.id, bindings):
                    found[spelling].append(call)
            elif isinstance(callee, ast.Attribute):
                found[callee.attr].append(Call(filename, node.lineno, node, True))
    return found


def position(fn, name):
    """Where ``name`` sits in the signature, or None if it is keyword-only."""
    positional = fn.args.posonlyargs + fn.args.args
    for i, arg in enumerate(positional):
        if arg.arg == name:
            return i
    return None


def binds_self(fn):
    """Does a bound call to this function consume the first parameter?

    Reading the decorator list is enough here: ``staticmethod`` takes no
    receiver, and ``classmethod`` takes one exactly as an instance method does.
    A module-level function whose first parameter is called ``self`` would be
    misread, which is rare enough to be worth the simplicity, and the misreading
    lands on the conservative side.
    """
    first = (fn.args.posonlyargs + fn.args.args)[:1]
    if not first or first[0].arg not in ("self", "cls"):
        return False
    for decorator in fn.decorator_list:
        label = decorator.id if isinstance(decorator, ast.Name) else getattr(decorator, "attr", "")
        if label == "staticmethod":
            return False
    return True


def supplies(call, name, index_in_signature, drop_self):
    """Does this call site pass the parameter? True, False, or None for unknown."""
    for keyword in call.node.keywords:
        if keyword.arg == name:
            return True
    if any(keyword.arg is None for keyword in call.node.keywords):
        return None  # a **splat could be carrying it
    if index_in_signature is None:
        return False  # keyword-only, and no keyword of that name was given
    if any(isinstance(arg, ast.Starred) for arg in call.node.args):
        return None  # a *splat could be filling the position
    wanted = index_in_signature - 1 if (drop_self and call.attribute) else index_in_signature
    if wanted < 0:
        return None
    return len(call.node.args) > wanted


@dataclass(frozen=True)
class Reach:
    """What the call sites collectively say about one parameter."""

    supplying: int
    omitting: tuple
    unknown: tuple

    @property
    def total(self):
        return self.supplying + len(self.omitting) + len(self.unknown)

    @property
    def unreachable(self):
        """True only when every call site was resolved and all of them supply it."""
        return self.total > 0 and not self.omitting and not self.unknown


def reach(fn, name, calls):
    """Read the call sites of ``fn`` for what they do with ``name``."""
    sites = calls.get(fn.name, ())
    where = position(fn, name)
    drop_self = binds_self(fn)

    supplying, omitting, unknown = 0, [], []
    for site in sites:
        answer = supplies(site, name, where, drop_self)
        if answer is True:
            supplying += 1
        elif answer is False:
            omitting.append(site)
        else:
            unknown.append(site)
    return Reach(supplying, tuple(omitting), tuple(unknown))
