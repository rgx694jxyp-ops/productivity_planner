# Module Ownership Rules

These rules define where new code should live and which directions imports can flow.

## Ownership

- `app.py`: shell only
- `pages/`: UI orchestration
- `services/`: workflows and integration coordination
- `domain/`: pure business logic
- `ui/`: presentational/reusable UI components
- `core/`: app infrastructure/runtime/bootstrap
- `utils/`: generic helpers

## Import Boundaries

- `app.py` may import from `core/` only.
- `domain/` must stay pure:
  - no `streamlit`
  - no imports from `core/`, `pages/`, `services/`, or `ui/`
- `services/` must not import from `pages/`.
- `services/` should stay frontend-agnostic:
  - no `streamlit`
  - no imports from `core/`
- `ui/` must not import from `pages/`.
- `utils/` must not import from app layers (`core/`, `pages/`, `services/`, `domain/`, `ui/`).

## Intent

These boundaries keep responsibilities obvious and prevent hidden coupling.
When adding code, place it in the highest-level module that still keeps logic reusable:

1. Pure formula/rules: `domain/`
2. Workflow/integration: `services/`
3. Rendering widgets/components: `ui/`
4. Page composition/interaction: `pages/`
5. Runtime/bootstrap/plumbing: `core/`

## Product Direction

When adding new product features, default toward execution-system concepts:

- actions
- follow-up
- unresolved issues
- outcomes

Do not default toward passive dashboard expansion unless it directly supports supervisor follow-through.
