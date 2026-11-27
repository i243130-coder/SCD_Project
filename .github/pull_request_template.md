## What does this PR do?
Closes #

## Checklist (reviewer: the *other* member)
- [ ] Conventional commit title (`feat(x): ...`, `fix(x): ...`, `test(x): ...`)
- [ ] Tests added/updated and green locally (`./scripts/test_all.sh`)
- [ ] Schemas re-exported if models changed (`python scripts/export_schemas.py`)
- [ ] Prompt/rubric version bumped if its content changed (`python scripts/check_registry.py`)
- [ ] No secrets, no `localhost` in images, no model weights
- [ ] AI-usage log row added if AI generated a significant part (`docs/ai-usage-log.md`)
- [ ] PROGRESS.md updated
