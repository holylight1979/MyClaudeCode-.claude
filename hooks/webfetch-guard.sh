#!/usr/bin/env bash
# WebFetch Guard — PreToolUse hook
# Blocks WebFetch if target URL doesn't respond within timeout
# Prevents indefinite hangs (e.g. 14-hour hang on unresponsive servers)

TIMEOUT_SECONDS=15

# Read hook input from stdin
INPUT=$(cat)

# Extract tool name
TOOL_NAME=$(echo "$INPUT" | python -c "import sys,json;print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)

# Only guard WebFetch calls
if [ "$TOOL_NAME" != "WebFetch" ]; then
  exit 0
fi

# Extract URL from tool input
URL=$(echo "$INPUT" | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('url',''))" 2>/dev/null)

if [ -z "$URL" ]; then
  exit 0
fi

# Probe URL with timeout (HEAD request first, fallback to GET with range)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SECONDS" --head "$URL" 2>/dev/null)
CURL_EXIT=$?

# If HEAD fails with HTTP error, try GET (some servers block HEAD)
if [ "$CURL_EXIT" -eq 0 ] && [ "$HTTP_CODE" -ge 400 ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT_SECONDS" -r 0-0 "$URL" 2>/dev/null)
  CURL_EXIT=$?
fi

if [ "$CURL_EXIT" -ne 0 ]; then
  # Timeout or connection error — block WebFetch
  cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","reason":"WebFetch guard: URL did not respond within ${TIMEOUT_SECONDS}s (curl exit=$CURL_EXIT). URL: $URL"}}
EOF
  exit 0
fi

# URL responded — allow WebFetch to proceed
exit 0
