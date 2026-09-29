"""Explicit workflow state machine.

The transition table is the single source of truth for what may follow what.
In particular there is **no** path from any audit/report state directly to
EXECUTING (it must pass through an approval state) and **no** path from
EXECUTING to COMPLETED (verification cannot be skipped).
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    IDLE = "IDLE"
    WAITING_FOR_STORE = "WAITING_FOR_STORE"
    DISCOVERING = "DISCOVERING"
    AUDITING = "AUDITING"
    REPORT_READY = "REPORT_READY"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    VERIFYING = "VERIFYING"
    RE_AUDITING = "RE_AUDITING"
    MERCHANT_APPROVAL_REQUIRED = "MERCHANT_APPROVAL_REQUIRED"
    MERCHANT_INSPECTING = "MERCHANT_INSPECTING"
    MERCHANT_REPORT_READY = "MERCHANT_REPORT_READY"
    MERCHANT_WRITE_APPROVAL_REQUIRED = "MERCHANT_WRITE_APPROVAL_REQUIRED"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED_SAFE = "FAILED_SAFE"


S = WorkflowState

# States in which a platform/store write may be authorised.
WRITE_STATES = frozenset({S.EXECUTING})

# States that may be interrupted by an auth/user-action pause and later resumed.
RESUMABLE_STATES = frozenset(
    {S.DISCOVERING, S.EXECUTING, S.VERIFYING, S.RE_AUDITING, S.MERCHANT_INSPECTING}
)

TERMINAL_STATES = frozenset({S.COMPLETED, S.PARTIALLY_COMPLETED, S.FAILED_SAFE})

TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    S.IDLE: frozenset({S.WAITING_FOR_STORE, S.DISCOVERING}),
    S.WAITING_FOR_STORE: frozenset({S.DISCOVERING, S.FAILED_SAFE}),
    S.DISCOVERING: frozenset(
        {S.AUDITING, S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED, S.FAILED_SAFE}
    ),
    S.AUDITING: frozenset({S.REPORT_READY, S.FAILED_SAFE}),
    S.REPORT_READY: frozenset(
        {
            S.WAITING_FOR_APPROVAL,
            S.MERCHANT_APPROVAL_REQUIRED,
            S.DISCOVERING,
            S.COMPLETED,
            S.PARTIALLY_COMPLETED,
        }
    ),
    S.WAITING_FOR_APPROVAL: frozenset(
        {
            S.WAITING_FOR_APPROVAL,  # clarification loop
            S.EXECUTING,
            S.MERCHANT_APPROVAL_REQUIRED,
            S.COMPLETED,
            S.PARTIALLY_COMPLETED,
        }
    ),
    S.EXECUTING: frozenset(
        {S.VERIFYING, S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED, S.FAILED_SAFE}
    ),
    S.AUTH_REQUIRED: frozenset(RESUMABLE_STATES | {S.FAILED_SAFE, S.PARTIALLY_COMPLETED}),
    S.USER_ACTION_REQUIRED: frozenset(RESUMABLE_STATES | {S.FAILED_SAFE, S.PARTIALLY_COMPLETED}),
    S.VERIFYING: frozenset({S.RE_AUDITING, S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED, S.FAILED_SAFE}),
    S.RE_AUDITING: frozenset(
        {
            S.COMPLETED,
            S.PARTIALLY_COMPLETED,
            S.WAITING_FOR_APPROVAL,
            S.MERCHANT_APPROVAL_REQUIRED,
            S.MERCHANT_REPORT_READY,
            S.FAILED_SAFE,
        }
    ),
    S.MERCHANT_APPROVAL_REQUIRED: frozenset(
        {S.MERCHANT_INSPECTING, S.MERCHANT_APPROVAL_REQUIRED, S.COMPLETED, S.PARTIALLY_COMPLETED}
    ),
    S.MERCHANT_INSPECTING: frozenset(
        {S.MERCHANT_REPORT_READY, S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED, S.FAILED_SAFE}
    ),
    S.MERCHANT_REPORT_READY: frozenset(
        {S.MERCHANT_WRITE_APPROVAL_REQUIRED, S.COMPLETED, S.PARTIALLY_COMPLETED}
    ),
    S.MERCHANT_WRITE_APPROVAL_REQUIRED: frozenset(
        {S.MERCHANT_WRITE_APPROVAL_REQUIRED, S.EXECUTING, S.COMPLETED, S.PARTIALLY_COMPLETED}
    ),
    S.COMPLETED: frozenset({S.DISCOVERING}),  # a fresh re-audit may start again
    S.PARTIALLY_COMPLETED: frozenset({S.DISCOVERING}),
    S.FAILED_SAFE: frozenset({S.DISCOVERING, S.WAITING_FOR_STORE}),
}


class IllegalTransition(RuntimeError):
    def __init__(self, current: WorkflowState, target: WorkflowState):
        super().__init__(f"illegal transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


class WorkflowMachine:
    def __init__(
        self,
        state: WorkflowState = S.IDLE,
        history: list[str] | None = None,
        resume_state: WorkflowState | None = None,
    ):
        self.state = state
        self.history: list[str] = list(history or [state.value])
        self.resume_state = resume_state

    def can(self, target: WorkflowState) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: WorkflowState) -> WorkflowState:
        if not self.can(target):
            raise IllegalTransition(self.state, target)
        if target in (S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED):
            if self.state in RESUMABLE_STATES:
                self.resume_state = self.state
        elif self.state in (S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED) and target in RESUMABLE_STATES:
            if self.resume_state is not None and target != self.resume_state:
                # Resuming must return exactly to where we paused.
                raise IllegalTransition(self.state, target)
            self.resume_state = None
        self.state = target
        self.history.append(target.value)
        return target

    def resume(self) -> WorkflowState:
        if self.state not in (S.AUTH_REQUIRED, S.USER_ACTION_REQUIRED) or self.resume_state is None:
            raise IllegalTransition(self.state, self.resume_state or self.state)
        return self.transition(self.resume_state)

    @property
    def allows_write(self) -> bool:
        return self.state in WRITE_STATES

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "history": self.history,
            "resume_state": self.resume_state.value if self.resume_state else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> WorkflowMachine:
        resume = d.get("resume_state")
        history = d.get("history")
        return cls(
            WorkflowState(str(d["state"])),
            list(history) if isinstance(history, list) else None,
            WorkflowState(str(resume)) if resume else None,
        )
