"""The three answers this tool gives, and why there are three rather than two.

A linter has two states, warned and silent. Reachability has a third, because
deciding whether a closure escapes sometimes depends on a function this tool
cannot see into. Collapsing that case into either "safe" or "bites" would be a
guess presented as an answer, so it gets its own verdict and names the function
the reader has to look at.
"""

from dataclasses import dataclass

BITES = "BITES"
SAFE = "SAFE"
CALLEE = "CALLEE"

#: Report order: the reader wants the actionable ones first.
ORDER = (BITES, CALLEE, SAFE)


@dataclass(frozen=True)
class Verdict:
    """One warning, decided.

    kind:   BITES, SAFE or CALLEE.
    reason: a sentence a reader can check against the source without rerunning
            anything. Never a restatement of the rule.
    """

    kind: str
    reason: str

    @property
    def actionable(self) -> bool:
        return self.kind == BITES

    def __str__(self) -> str:
        return f"{self.kind}: {self.reason}"
