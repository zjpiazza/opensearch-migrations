# Migration contracts

This directory is the entry point for contract ownership during the architecture
refactor. The current schema implementation remains in the existing npm workspace
at [apps/orchestration/packages/schemas](../apps/orchestration/packages/schemas).
Worker contracts remain beside their Java implementations. No duplicate schema
definitions or new operator API are introduced by the directory relocation.

Moving to a versioned, independently generated migration/worker API is tracked as
D-002 and D-003 in the [decision register](../docs/architecture-refactor/decisions.md).
