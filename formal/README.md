# Formal layer

`TasksKiller.tla` is the state machine: phases, AI review before each of the two human gates, exclusive segment locks, and recovery. `TasksKiller.cfg` is the TLC configuration for two segments that share one resource.

`check_model.py` enumerates the same rules, including a second configuration where one segment needs no lock. It is what CI can run when TLC is absent:

```sh
python -B formal/check_model.py
```

TLC, from a directory that contains `tla2tools.jar`:

```sh
java -cp tla2tools.jar tlc2.TLC -config formal/TasksKiller.cfg formal/TasksKiller.tla
```

`TasksKiller.lean` proves three ledger obligations: a fresh lock is not stale and can be broken only when forced; replacing one evidence digest invalidates the binder; `done` and each human flag require the matching AI pass.

```sh
lean formal/TasksKiller.lean
```
