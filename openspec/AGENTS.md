# OpenSpec Workflow

This project uses OpenSpec for spec-driven development.

## Workflow

1. **Create Change Proposal**: Start with a change proposal describing what you want to build
2. **Define Specs**: Create or update specification documents with requirements
3. **Track Tasks**: Break down work into tasks and track progress
4. **Implement**: Build according to the specs
5. **Validate**: Ensure specs are followed
6. **Archive**: Archive completed changes

## Commands

- Create a change: "Create an OpenSpec change proposal for [feature]"
- List changes: "Show me all OpenSpec changes"
- View change: "Show me the details of change [change-id]"
- Update tasks: "Mark task [task-id] as complete in change [change-id]"
- Validate: "Validate the OpenSpec change [change-id]"
- Archive: "Archive the OpenSpec change [change-id]"

## File Structure

```
openspec/
├── project.md          # Project context and conventions
├── AGENTS.md           # This file
├── specs/              # Specification documents
│   └── [capability]/
│       └── spec.md
└── changes/            # Active changes
    ├── [change-id]/
    │   ├── proposal.md
    │   ├── tasks.md
    │   ├── design.md (optional)
    │   └── specs/
    │       └── [capability]/
    │           └── spec.md
    └── archive/        # Completed changes
```

## Best Practices

1. Always start with a clear change proposal
2. Define requirements before implementation
3. Keep specs up to date
4. Track progress with tasks
5. Validate before archiving
