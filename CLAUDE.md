# Atlas Agent Instructions

When working on tasks related to n8n workflows, nodes, expressions, validation, troubleshooting, or workflow architecture:

- Prioritize the installed n8n skills before solving from scratch.
- Use `n8n-workflow-patterns` for workflow design and composition.
- Use `n8n-node-configuration` for node setup details and parameter choices.
- Use `n8n-expression-syntax` for expressions and data mapping.
- Use `n8n-validation-expert` to review or validate workflow JSON before finalizing.
- Use `n8n-code-javascript` or `n8n-code-python` when a Code node is involved.
- Use the configured n8n MCP server when the task needs live data from the n8n instance, such as listing workflows, checking node docs, validating against live capabilities, or updating workflows.

## Expected Behavior

- Prefer using both skills and MCP together when creating or editing real n8n workflows.
- Validate workflow structure before presenting the final result.
- If a request is ambiguous, assume the user wants an n8n-ready solution rather than a generic example.
- When possible, produce output that can be pasted into n8n directly or applied through the MCP tools.
