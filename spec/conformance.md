# APX 0.1 Conformance

A Provider is conforming when its manifest and schemas validate, its Action IDs are
unique, it preserves the pre-commit boundary, performs each idempotent logical request
once, rechecks policy and state before commit, binds and consumes confirmation, reports
denial without bypass, verifies postconditions, supports status/receipt recovery, and
redacts secrets.

A Client is conforming when it respects confirmation and expiry, does not mutate
confirmed intent, obeys retry/cooldown/rate metadata, does not retry unsafe ambiguous
execution, does not treat authentication as authority, accepts Provider denial, and
does not claim completion without a completed verified result/receipt when required.

The reusable Python suite is in `apx.conformance`. The independent TypeScript client
fixture in `interop/typescript` consumes only JSON messages and the published schemas.
