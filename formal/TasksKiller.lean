/-
Critical invariants for tasks-killer, checked as definitions rather than comments.

  lake env lean formal/TasksKiller.lean

or, with a single file and no lake project:

  lean formal/TasksKiller.lean

The proofs cover three obligations the Python ledger relies on:
a lock cannot be both fresh and stale; an evidence binder does not survive a
changed digest; a human gate and `done` require the matching AI pass.
-/

namespace TasksKiller

/-- A resource lock as the ledger and resource_lock.py treat it. -/
structure Lock where
  leaseExpired : Bool
  holderAlive : Bool
  forced : Bool
deriving Repr

/-- Stale means the lease ran out or the holder process is gone. -/
def Lock.stale (lock : Lock) : Bool :=
  lock.leaseExpired || !lock.holderAlive

/-- Breaking a live lock is the forced path. The normal path is staleness. -/
def Lock.mayBreak (lock : Lock) : Bool :=
  lock.stale || lock.forced

theorem fresh_not_stale (lock : Lock)
    (lease : lock.leaseExpired = false) (alive : lock.holderAlive = true) :
    lock.stale = false := by
  simp [Lock.stale, lease, alive]

theorem break_of_fresh_requires_force (lock : Lock)
    (lease : lock.leaseExpired = false) (alive : lock.holderAlive = true)
    (broken : lock.mayBreak = true) :
    lock.forced = true := by
  have h := fresh_not_stale lock lease alive
  simp [Lock.mayBreak, h] at broken
  exact broken

/-- The digest sealed for one piece of evidence. -/
structure Sealed where
  digest : Nat
deriving DecidableEq, Repr

/-- The binder stores that same digest. -/
structure Binder where
  digest : Nat
deriving DecidableEq, Repr

def bound (evidence : Sealed) (binder : Binder) : Prop :=
  evidence.digest = binder.digest

theorem binder_matches_evidence (evidence : Sealed) :
    bound evidence { digest := evidence.digest } := rfl

theorem changed_digest_unbounds
    (evidence : Sealed) (binder : Binder) (fresh : Nat)
    (ok : bound evidence binder)
    (changed : fresh ≠ evidence.digest) :
    ¬ bound { digest := fresh } binder := by
  intro rebound
  have freshIsBinder : fresh = binder.digest := rebound
  have freshIsOld : fresh = evidence.digest := by
    rw [freshIsBinder, ok.symm]
  exact changed freshIsOld

/-- Workflow phases named the same way as scripts/workflow_state.py. -/
inductive Phase
  | intake
  | goalReview
  | awaitingConfirmation
  | produce
  | review
  | awaitingFinal
  | done
deriving DecidableEq, Repr

structure World where
  phase : Phase
  goalAI : Bool
  goalHuman : Bool
  finalAI : Bool
  finalHuman : Bool
deriving Repr

/-- What a legal world is allowed to claim. -/
def World.gates (w : World) : Prop :=
  (w.goalHuman = true → w.goalAI = true) ∧
  (w.finalHuman = true → w.finalAI = true) ∧
  (w.phase = Phase.awaitingConfirmation → w.goalAI = true) ∧
  (w.phase = Phase.produce → w.goalHuman = true) ∧
  (w.phase = Phase.awaitingFinal → w.finalAI = true) ∧
  (w.phase = Phase.done → w.goalHuman = true ∧ w.finalHuman = true)

theorem done_has_both_human_gates (w : World) (h : w.gates) (done : w.phase = Phase.done) :
    w.goalHuman = true ∧ w.finalHuman = true := by
  exact h.2.2.2.2.2 done

theorem done_has_both_ai_passes (w : World) (h : w.gates) (done : w.phase = Phase.done) :
    w.goalAI = true ∧ w.finalAI = true := by
  have humans := done_has_both_human_gates w h done
  constructor
  · exact h.1 humans.1
  · exact h.2.1 humans.2

theorem human_goal_requires_ai (w : World) (h : w.gates) (human : w.goalHuman = true) :
    w.goalAI = true := h.1 human

theorem human_final_requires_ai (w : World) (h : w.gates) (human : w.finalHuman = true) :
    w.finalAI = true := h.2.1 human

end TasksKiller
