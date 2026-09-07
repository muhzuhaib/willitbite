"""The answers this tool gives, and why there are more than two.

A linter has two states, warned and silent. Reachability needs more, because
twice over the honest answer is neither.

CALLEE exists because deciding whether a closure escapes sometimes depends on a
function this tool cannot see into. LATENT exists because a function can be
genuinely wrong and still be unreachable: a mutable default that the function
mutates is a defect, but it only fires when some caller omits the argument, and
sometimes no caller does. Collapsing either case into "safe" or "bites" would be
a guess presented as an answer, so each gets its own verdict and names the thing
the reader has to look at.
"""

from dataclasses import dataclass

BITES = "BITES"
LATENT = "LATENT"
SAFE = "SAFE"
CALLEE = "CALLEE"

#: Report order: the reader wants the actionable ones first.
ORDER = (BITES, LATENT, CALLEE, SAFE)


@dataclass(frozen=True)
class Verdict:
    """One warning, decided.

    kind:   BITES, LATENT, CALLEE or SAFE.
    reason: a sentence a reader can check against the source without rerunning
            anything. Never a restatement of the rule.
    """

    kind: str
    reason: str

    @property
    def actionable(self) -> bool:
        """Can this reach you as the code stands today?

        LATENT is deliberately excluded. It is a real defect and it is reported
        as one, but nothing calls it in a way that triggers it, so failing a
        build on it would fail every build until somebody rewrote code that
        currently works.
        """
        return self.kind == BITES

    def __str__(self) -> str:
        return f"{self.kind}: {self.reason}"
