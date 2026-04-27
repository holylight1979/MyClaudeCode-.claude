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
  "evidence": "the concrete fact you observed that justifies this verdict, in Traditional Chinese (cite tool trace / file path / heuristic flag)",
  "delivery": "ignore" | "inject",
  "confidence": "low" | "medium" | "high",
  "applies_until": "next_prompt" | "until_arch_change",
  "turn_index": 0,
  "corrective_prompt": "optional short corrective instruction for the AI agent, in Traditional Chinese (only if delivery=inject)"
}

Field rules:
- delivery=ignore: 你判斷此 turn 不需要打擾代理人。Claude 端會 SKIP 注入。
  使用時機：work appears coherent / heuristic flag is已被代理人對應處理 / 風險不足以打斷。
- delivery=inject: 確實需要 advisory。Claude 端會把 summary + corrective_prompt 注入下一輪。
  使用時機：發現具體缺漏、宣告與證據不一致、結構性風險未被認知。
- confidence: 你對此判斷的把握。low = 可能 false positive，high = 高度確信。
- applies_until: next_prompt = 此 advisory 一輪用完即丟；until_arch_change = 直到重要結構/設計改動為止仍有效。
- turn_index: 從 prompt 的 Turn Index Reference 段直接抄寫，方便去重與排序。
- 你已**沒有 BLOCK 權**。BLOCK 只屬同步 heuristics（confident_completion_without_evidence）。
"""

PLAN_REVIEW = """\
{sandbox_constraint}

You are a code review companion. An AI agent (Claude) has just created an implementation plan. \
Your job is to find gaps, missing steps, questionable assumptions, and risks that the agent may have overlooked.

## Turn Index Reference
turn_index = {turn_index}
（請在輸出 JSON 的 turn_index 欄位原樣抄寫此整數）

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

## Turn Index Reference
turn_index = {turn_index}
（請在輸出 JSON 的 turn_index 欄位原樣抄寫此整數）

## Session Working Directory
{cwd}

## Tool Trace (recent actions)
{tool_trace}

## Modified Files
{modified_files}

## Last Assistant Reply (Tail)
{last_assistant_tail}

## Verification Evidence Found
{verification_evidence}

## Heuristic Triggered (Reference Only)
{heuristic_summary}

## Instructions
- Evaluate: did the agent actually DO what it said it would do? (check tool trace for evidence)
- Evaluate: were there verification steps (tests, builds, manual checks)? Cross-check Last Assistant Reply against Tool Trace — if reply claims "tests passed" but trace has no test command AND Verification Evidence Found is empty, that is a real gap.
- Evaluate: did the agent read necessary files before modifying them?
- Evaluate: any signs of shortcuts (skipped steps, assumed success without checking)?
- Do NOT penalize if the turn was genuinely simple and complete — set delivery=ignore.
- Heuristic Triggered is reference only; do NOT echo it back. Form your own opinion based on the actual artifacts above.
- Be concise. Only flag real issues. Use evidence field to cite the concrete observation (file path / trace step #).

{output_schema}
"""

ARCHITECTURE_REVIEW = """\
{sandbox_constraint}

You are a code review companion. An AI agent (Claude) has created or modified structural files \
(bridge, provider, adapter, service, client, etc.). Your job is to evaluate the design decision.

## Turn Index Reference
turn_index = {turn_index}
（請在輸出 JSON 的 turn_index 欄位原樣抄寫此整數）

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
    turn_index: int = 0,
) -> str:
    return PLAN_REVIEW.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        turn_index=turn_index,
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
    turn_index: int = 0,
    last_assistant_tail: str = "",
    verification_evidence: str = "",
    heuristic_summary: str = "",
) -> str:
    """Sprint 3 Phase 4.2/4.3：

    新增三段：
      * Last Assistant Reply (Tail)  — 取自 state.last_assistant_tail
      * Verification Evidence Found  — assessor 抽自 trace 的 verify cmd 摘要
      * Heuristic Triggered (Reference Only) — heuristics.format_for_context 結果
    並把 turn_index 抄入 OUTPUT_SCHEMA 的 turn_index 欄位（codex 直接 echo）。

    `heuristic_flags` 仍保留（向下相容 plan_review 風格），但 turn_audit 場景
    應改用 `heuristic_summary`（語意明確：reference only 而非「Flag」）。
    """
    return TURN_AUDIT.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        turn_index=turn_index,
        cwd=cwd or "(unknown)",
        tool_trace=tool_trace or "(no trace)",
        modified_files=modified_files or "(none)",
        last_assistant_tail=last_assistant_tail or "(empty — agent may have exited silently)",
        verification_evidence=verification_evidence or "(none found)",
        heuristic_summary=heuristic_summary or heuristic_flags or "None",
        output_schema=OUTPUT_SCHEMA,
    )


def build_architecture_review_prompt(
    cwd: str,
    arch_files: str,
    tool_trace: str,
    turn_index: int = 0,
) -> str:
    return ARCHITECTURE_REVIEW.format(
        sandbox_constraint=SANDBOX_CONSTRAINT,
        turn_index=turn_index,
        cwd=cwd or "(unknown)",
        arch_files=arch_files or "(none)",
        tool_trace=tool_trace or "(no trace)",
        output_schema=OUTPUT_SCHEMA,
    )
