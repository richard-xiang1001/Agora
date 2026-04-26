## Output Mode: json_claim_v1 (MANDATORY)

Return EXACTLY one JSON object. No markdown. No code fences. No prose.

Required keys (all required):
agent_id, task_intent, risk_level, reversibility, tool_need, conclusion, evidence, assumptions, confidence

Allowed enums:
task_intent: code_review | research | planning | general | unknown
risk_level: low | medium | high
reversibility: reversible | partial | irreversible
confidence: low | medium | high

Type constraints:
agent_id: string (non-empty)
tool_need: boolean
conclusion: string (non-empty)
evidence: array[string], minItems=1
assumptions: array[string], minItems=1

Output JSON shape:
{
  "agent_id": "...",
  "task_intent": "code_review|research|planning|general|unknown",
  "risk_level": "low|medium|high",
  "reversibility": "reversible|partial|irreversible",
  "tool_need": true,
  "conclusion": "...",
  "evidence": ["..."],
  "assumptions": ["..."],
  "confidence": "low|medium|high"
}
