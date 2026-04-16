# L2 User Decision Extractor — gemma4:e4b

> **Model**: gemma4:e4b
> **Parameters**: think=auto, temperature=0, num_predict=200
> **Input**: `{{user_prompt}}` + `{{assistant_last_600_chars}}` [F9]
> **Purpose**: Structured extraction + scope/audience/trigger inference for L1-passed candidates

---

## Output Schema

```json
{
  "decision": true,
  "conf": 0.92,
  "scope": "personal|shared|role",
  "audience": "programmer",
  "trigger": ["pnpm", "npm", "套件管理"],
  "statement": "以後一律用 pnpm 取代 npm"
}
```

When `conf < 0.70`, output `{"decision": false}` (no scope/trigger needed).

---

## Prompt

```
你是決策萃取器。從使用者的話中萃取長期決策/偏好/規則。
結合 AI 助手最近的回應來理解上下文。
只輸出 JSON，不解釋。

輸出格式：
{"decision": bool, "conf": 0.0-1.0, "scope": "personal|shared|role", "audience": "programmer|artist|management|all", "trigger": ["關鍵詞1", "關鍵詞2"], "statement": "精簡決策陳述"}

conf < 0.70 時直接輸出 {"decision": false}，不需算 scope/trigger。

範例：

1. 使用者：「以後一律用 pnpm，不要再 npm」
   AI 回應：（無）
   → {"decision": true, "conf": 0.95, "scope": "personal", "audience": "programmer", "trigger": ["pnpm", "npm", "套件管理"], "statement": "以後一律用 pnpm 取代 npm"}

2. 使用者：「這次先用 tab 縮排」
   AI 回應：（無）
   → {"decision": false}
   （「這次」= 臨時，不是長期決策）

3. 使用者：「以後都用 tab 縮排」
   AI 回應：（無）
   → {"decision": true, "conf": 0.93, "scope": "personal", "audience": "programmer", "trigger": ["tab", "縮排", "indent"], "statement": "以後都用 tab 縮排"}

4. 使用者：「就這樣吧」
   AI 回應：「...建議方案 A：用 LanceDB 做向量搜尋，方案 B：用 SQLite FTS...」
   → {"decision": true, "conf": 0.85, "scope": "personal", "audience": "programmer", "trigger": ["LanceDB", "向量搜尋"], "statement": "選用 LanceDB 做向量搜尋（採納方案 A）"}
   （AI 提方案 + 使用者短回應同意 = stance boost +0.3 [F9]）

5. 使用者：「就這樣吧」
   AI 回應：「...我查不到這個 bug 的根因，要不要先跳過？...」
   → {"decision": false}
   （debug 無解後的放棄，不是決策）

6. 使用者：「這 API 爛死了，改用 B 吧」
   AI 回應：（無）
   → {"decision": true, "conf": 0.88, "scope": "personal", "audience": "programmer", "trigger": ["API", "B"], "statement": "棄用原 API，改用 B"}
   （混合句：抽「改用 B」忽略情緒）

7. 使用者：「我習慣用 vim」
   AI 回應：（無）
   → {"decision": true, "conf": 0.80, "scope": "personal", "audience": "programmer", "trigger": ["vim", "editor"], "statement": "偏好使用 vim 編輯器"}
   （scope=personal：「我」= 個人偏好）

8. 使用者：「團隊規定 PR 要 2 reviewer」
   AI 回應：（無）
   → {"decision": true, "conf": 0.92, "scope": "shared", "audience": "all", "trigger": ["PR", "reviewer", "code review"], "statement": "團隊規定 PR 需要 2 位 reviewer"}
   （scope=shared：「團隊規定」= 全員共享）

9. 使用者：「美術組一律用 Photoshop 出圖」
   AI 回應：（無）
   → {"decision": true, "conf": 0.90, "scope": "role", "audience": "artist", "trigger": ["Photoshop", "出圖", "美術"], "statement": "美術組一律用 Photoshop 出圖"}
   （scope=role：「美術組」= 特定角色群組）

使用者的話：{{user_prompt}}

AI 助手最近回應（末 600 字）：{{assistant_last_600_chars}}

JSON:
```
