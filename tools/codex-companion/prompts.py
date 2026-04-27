"""prompts.py — Prompt templates for Codex Companion assessments.

All prompts instruct Codex to output structured JSON.
Placeholders use {name} format for str.format().
"""

SANDBOX_CONSTRAINT = """\
【硬性沙盒約束】本任務純讀取與分析。禁止任何 git/edit/write/rm/mv/mkdir/touch \
/cp 等修改型指令；禁止呼叫 npm install/pip install 等下載安裝指令。\
僅允許 cat/grep/rg/Get-Content/Get-ChildItem/Select-String 等讀取指令。\
違反即任務失敗。
"""

OUTPUT_SCHEMA = """\
You MUST respond with a single JSON object (no markdown fences, no extra text):
{
  "status": "ok" | "warning" | "needs_followup",
  "severity": "low" | "medium" | "high",
  "category": "plan_gap" | "missing_evidence" | "laziness" | "architecture_risk" | "completion_risk",
  "summary": "one-line summary in Traditional Chinese",
  "recommended_action": "specific actionable suggestion in Traditional Chinese",
  "corrective_prompt": "optional short corrective instruction for the AI agent, in Traditional Chinese"
}
"""

PLAN_REVIEW = """\
{sandbox_constraint}

You are a code review companion. An AI agent (Claude) has just created an implementation plan. \
Your job is to find gaps, missing steps, questionable assumptions, and risks that the agent may have overlooked.

## User's Original Goal
{user_goal}

## Plan Content
{plan_content}

## Files Examined by the Agent
{files_examined}

## Heuristic Flags (if any)
{heuristic_flags}

## Instructions
- Focus on what is MISSING, not what is present
- Check: are there steps that depend on untested assumptions?
- Check: is there a verification/testing step after implementation?
- Check: are edge cases or failure modes considered?
- Check: is the scope appropriate, or is it too broad/narrow?
- Be concise and specific. Do not praise or encourage. Only point out problems or confirm "ok".

{output_schema}
"""

TURN_AUDIT = """\
{sandbox_constraint}

You are a code review companion. An AI agent (Claude) has just completed a work turn. \
Your job is to evaluate whether the work was thorough, whether shortcuts were taken, \
and whether the results have sufficient evidence.

## Session Working Directory
{cwd}

## Tool Trace (recent actions)
{tool_trace}

## Modified Files
{modified_files}

## Heuristic Flags
{heuristic_flags}

## Instructions
- Evaluate: did the agent actually DO what it said it would do? (check tool trace for evidence)
- Evaluate: were there verification steps (tests, builds, manual checks)?
- Evaluate: did the agent read necessary files before modifying them?
- Evaluate: any signs of shortcuts (skipped steps, assumed success without checking)?
- Do NOT penalize if the turn was genuinely simple and complete
- Be concise. Only flag real issues.

{output_schema}
"""

ARCHITECTURE_REVIEW = """\
{sandbox_constraint}

You are a code review companion. An AI agent (Claude) has created or modified structural files \
(bridge, provider, adapter, service, client, etc.). Your job is to evaluate the design decision.

## Session Working Directory
{cwd}

## Structural Files Changed
{arch_files}

## Recent Tool Trace
{tool_trace}

## Instructions
- Check: were alternatives considered?
- Check: is the abstraction level appropriate (too much? too little?)
- Check: are failure modes and rollback strategies addressed?
- Check: does this introduce unnecessary coupling?
- If the change is straightforward and appropriate, respond with status "ok"

{output_schema}
"""


def build_plan_review_prompt(
    user_goal: str,
    plan_content: str,
    files_examined: str,
    heuristic_flags: str = "None",
) -> str:
    return PLAN_REVIEW.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        user_goal=user_goal or "(not captured)",
        plan_content=plan_content or "(no plan content available)",
        files_examined=files_examined or "(none)",
        heuristic_flags=heuristic_flags,
        output_schema=OUTPUT_SCHEMA,
    )


def build_turn_audit_prompt(
    cwd: str,
    tool_trace: str,
    modified_files: str,
    heuristic_flags: str = "None",
) -> str:
    return TURN_AUDIT.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        cwd=cwd or "(unknown)",
        tool_trace=tool_trace or "(no trace)",
        modified_files=modified_files or "(none)",
        heuristic_flags=heuristic_flags,
        output_schema=OUTPUT_SCHEMA,
    )


def build_architecture_review_prompt(
    cwd: str,
    arch_files: str,
    tool_trace: str,
) -> str:
    return ARCHITECTURE_REVIEW.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        cwd=cwd or "(unknown)",
        arch_files=arch_files or "(none)",
        tool_trace=tool_trace or "(no trace)",
        output_schema=OUTPUT_SCHEMA,
    )
