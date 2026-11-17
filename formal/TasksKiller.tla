------------------------------ MODULE TasksKiller ------------------------------
\* State machine for tasks-killer.
\* Phases, the two human gates, AI review before each gate, exclusive locks,
\* and recovery. Python formal/check_model.py enumerates the same rules.
\*
\* TLC:
\*   java -cp tla2tools.jar tlc2.TLC -config formal/TasksKiller.cfg formal/TasksKiller.tla
\* The model is finite: two segments and one resource name.

EXTENDS FiniteSets, Sequences, TLC

CONSTANTS Segments, Resource, ExecutionRequired

VARIABLES
    phase,          \* intake | goal_review | awaiting_confirmation | produce
                    \* | review | awaiting_final | done | blocked
    goalAI,         \* independent reviewer passed the current goal
    goalHuman,      \* human confirmed that goal
    finalAI,        \* independent reviewer passed the current result
    finalHuman,     \* human confirmed the final result
    seg,            \* segment id -> pending | running | verified | rework
    lock,           \* resource holder segment, or "none"
    blockedFrom

vars == <<phase, goalAI, goalHuman, finalAI, finalHuman, seg, lock, blockedFrom>>

Phase == {
    "intake", "goal_review", "awaiting_confirmation", "produce",
    "review", "awaiting_final", "done", "blocked"
}
SegStatus == {"pending", "running", "verified", "rework"}

TypeOK ==
    /\ phase \in Phase
    /\ goalAI \in BOOLEAN /\ goalHuman \in BOOLEAN
    /\ finalAI \in BOOLEAN /\ finalHuman \in BOOLEAN
    /\ seg \in [Segments -> SegStatus]
    /\ lock \in Segments \union {"none"}
    /\ blockedFrom \in Phase \union {"none"}

BothVerified == \A s \in Segments : seg[s] = "verified"

ExclusiveBusy(s) ==
    \E t \in Segments : t /= s /\ seg[t] = "running"

\* Both modeled segments share Resource. A non-shared segment is not in this
\* finite spec; formal/check_model.py also checks that configuration.

Init ==
    /\ phase = "intake"
    /\ goalAI = FALSE /\ goalHuman = FALSE
    /\ finalAI = FALSE /\ finalHuman = FALSE
    /\ seg = [s \in Segments |-> "pending"]
    /\ lock = "none"
    /\ blockedFrom = "none"

SubmitGoal ==
    /\ phase = "intake"
    /\ phase' = "goal_review"
    /\ goalAI' = FALSE /\ goalHuman' = FALSE
    /\ UNCHANGED <<finalAI, finalHuman, seg, lock, blockedFrom>>

AIGoalPass ==
    /\ phase = "goal_review"
    /\ phase' = "awaiting_confirmation"
    /\ goalAI' = TRUE
    /\ UNCHANGED <<goalHuman, finalAI, finalHuman, seg, lock, blockedFrom>>

AIGoalRework ==
    /\ phase = "goal_review"
    /\ goalAI' = FALSE
    /\ UNCHANGED <<phase, goalHuman, finalAI, finalHuman, seg, lock, blockedFrom>>

AIGoalConflict ==
    /\ phase = "goal_review"
    /\ phase' = "blocked"
    /\ blockedFrom' = "goal_review"
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock>>

HumanGoal ==
    /\ phase = "awaiting_confirmation"
    /\ goalAI
    /\ phase' = "produce"
    /\ goalHuman' = TRUE
    /\ UNCHANGED <<goalAI, finalAI, finalHuman, seg, lock, blockedFrom>>

Claim(s) ==
    /\ phase = "produce" /\ goalHuman
    /\ seg[s] \in {"pending", "rework"}
    /\ lock = "none"
    /\ ~ExclusiveBusy(s)
    /\ seg' = [seg EXCEPT ![s] = "running"]
    /\ lock' = s
    /\ finalAI' = FALSE /\ finalHuman' = FALSE
    /\ UNCHANGED <<phase, goalAI, goalHuman, blockedFrom>>

Verify(s) ==
    /\ phase = "produce" /\ goalHuman
    /\ seg[s] = "running"
    /\ lock = s
    /\ seg' = [seg EXCEPT ![s] = "verified"]
    /\ lock' = "none"
    /\ UNCHANGED <<phase, goalAI, goalHuman, finalAI, finalHuman, blockedFrom>>

Rework(s) ==
    /\ phase = "produce" /\ goalHuman
    /\ seg[s] \in {"running", "verified"}
    /\ seg' = [seg EXCEPT ![s] = "rework"]
    /\ lock' = IF lock = s THEN "none" ELSE lock
    /\ finalAI' = FALSE /\ finalHuman' = FALSE
    /\ UNCHANGED <<phase, goalAI, goalHuman, blockedFrom>>

Recover(s) ==
    /\ phase = "produce"
    /\ seg[s] = "running"
    /\ seg' = [seg EXCEPT ![s] = "rework"]
    /\ lock' = IF lock = s THEN "none" ELSE lock
    /\ UNCHANGED <<phase, goalAI, goalHuman, finalAI, finalHuman, blockedFrom>>

SubmitResult ==
    /\ phase = "produce" /\ goalHuman
    /\ ~ExecutionRequired \/ BothVerified
    /\ \A s \in Segments : seg[s] /= "running"
    /\ phase' = "review"
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock, blockedFrom>>

AIFinalPass ==
    /\ phase = "review" /\ goalHuman
    /\ phase' = "awaiting_final"
    /\ finalAI' = TRUE
    /\ UNCHANGED <<goalAI, goalHuman, finalHuman, seg, lock, blockedFrom>>

AIFinalRework ==
    /\ phase = "review" /\ goalHuman
    /\ phase' = "produce"
    /\ finalAI' = FALSE /\ finalHuman' = FALSE
    /\ UNCHANGED <<goalAI, goalHuman, seg, lock, blockedFrom>>

AIFinalConflict ==
    /\ phase = "review" /\ goalHuman
    /\ phase' = "blocked"
    /\ blockedFrom' = "review"
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock>>

HumanFinal ==
    /\ phase = "awaiting_final" /\ finalAI
    /\ finalHuman' = TRUE
    /\ UNCHANGED <<phase, goalAI, goalHuman, finalAI, seg, lock, blockedFrom>>

Finish ==
    /\ phase = "awaiting_final" /\ finalAI /\ finalHuman
    /\ ~ExecutionRequired \/ BothVerified
    /\ phase' = "done"
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock, blockedFrom>>

InvalidateResult ==
    /\ phase = "done"
    /\ phase' = "review"
    /\ finalAI' = FALSE /\ finalHuman' = FALSE
    /\ UNCHANGED <<goalAI, goalHuman, seg, lock, blockedFrom>>

Pause ==
    /\ phase \notin {"blocked", "done"}
    /\ phase' = "blocked"
    /\ blockedFrom' = phase
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock>>

Resume ==
    /\ phase = "blocked"
    /\ blockedFrom /= "none"
    /\ phase' = blockedFrom
    /\ blockedFrom' = "none"
    /\ UNCHANGED <<goalAI, goalHuman, finalAI, finalHuman, seg, lock>>

Next ==
    \/ SubmitGoal \/ AIGoalPass \/ AIGoalRework \/ AIGoalConflict \/ HumanGoal
    \/ SubmitResult \/ AIFinalPass \/ AIFinalRework \/ AIFinalConflict
    \/ HumanFinal \/ Finish \/ InvalidateResult \/ Pause \/ Resume
    \/ \E s \in Segments : Claim(s) \/ Verify(s) \/ Rework(s) \/ Recover(s)

Spec == Init /\ [][Next]_vars

Gates ==
    /\ goalHuman => goalAI
    /\ finalHuman => finalAI
    /\ phase \in {"produce", "review", "awaiting_final", "done"} => goalHuman
    /\ phase = "awaiting_confirmation" => goalAI
    /\ phase = "awaiting_final" => finalAI
    /\ phase = "done" => goalHuman /\ finalHuman /\ goalAI /\ finalAI
                    /\ (~ExecutionRequired \/ BothVerified)

Exclusive ==
    /\ \A s, t \in Segments :
        s /= t /\ seg[s] = "running" /\ seg[t] = "running" => FALSE
    /\ lock /= "none" => seg[lock] = "running"
    /\ \A s \in Segments : seg[s] = "running" => lock = s

=============================================================================
