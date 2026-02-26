name: code_review
description: Security-focused code review workflow
version: "1.0"
permissions_scope: scope_code_review
preferred_models:
  - claude-3.7
  - gpt-4.5
input_schema:
  - field: code_content
    type: text
output_schema:
  - field: findings
  - field: confidence
  - field: assumptions
verification_strategy: minimal_poc_in_sandbox
