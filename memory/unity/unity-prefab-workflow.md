# Prefab 程式化建立 SOP

- Scope: global
- Confidence: [臨]
- Trigger: prefab SOP, 程式化建立 prefab, generate-ui-prefab, WndForm 建立
- Last-used: 2026-03-25
- Confirmations: 4
- Related: unity-yaml, unity-prefab-component-guids, unity-wndform-yaml-template

## 知識

### 工具鏈

| Tool | Path | 用途 |
|------|------|------|
| unity-yaml-tool.py | `~/.claude/tools/unity-yaml-tool.py` | generate-ui-prefab / validate / generate-meta |
| ClaudeEditorHelper.cs | `sgi_client/client/Assets/Editor/ClaudeEditorHelper.cs` | AutoGenUICode / ValidatePrefab (batch mode) |
| unity_batch.py | `~/.claude/tools/unity-desktop/unity_batch.py` | 執行 Unity batch method |

### Step 1: 設計 JSON Spec

```json
{
  "name": "WndForm_XXX",
  "children": [
    {"name": "Load_Title", "type": "Text", "anchor": "top-center", "size": {"x": 600, "y": 60}},
    {"name": "Confirm", "type": "UIButtonCustom", "anchor": "bottom-center", "size": {"x": 200, "y": 60}},
    {"name": "Scroller", "type": "Scroller", "anchor": "stretch", "scroll_class": "XXXScroller"}
  ]
}
```

**支援的 child type**: Text, Image, UIButtonCustom, Scroller, Empty
**支援的 anchor preset**: stretch, top-left, top-center, top-right, center, bottom-center, ...（共 14 種）

### Step 2: 生成 Prefab + Meta

```bash
python unity-yaml-tool.py generate-ui-prefab spec.json Assets/Res/UI/WndForm/WndForm_XXX.prefab
python unity-yaml-tool.py generate-meta Assets/Res/UI/WndForm/WndForm_XXX.prefab.meta --importer PrefabImporter
```

### Step 3: 靜態驗證

```bash
python unity-yaml-tool.py validate Assets/Res/UI/WndForm/WndForm_XXX.prefab
```

檢查：fileID 交叉引用、m_Script 非零、m_GameObject 引用

### Step 4: Unity 在線驗證

**方法 A — Unity Editor 已開啟（推薦）**：
1. 存檔後切回 Unity → 自動 Refresh
2. 若 prefab 正在 Prefab Mode 中開啟 → Unity 彈出 "Prefab has Been Changed on Disk" 對話框 → 點 **"Discard Changes"** 載入新版
3. 檢查 Console：先按 **Clear** 清掉舊訊息，確認無新 Warning/Error
4. 用 MCPControl 或 PowerShell 截圖確認 Console 狀態

**方法 B — Unity Editor 關閉時（batch mode）**：
```bash
python unity_batch.py -p sgi_client/client -m ClaudeEditorHelper.RefreshAssets
python unity_batch.py -p sgi_client/client -m ClaudeEditorHelper.ValidatePrefab --extra-args "-prefab Assets/Res/UI/WndForm/WndForm_XXX.prefab"
```

### Step 5: AutoGenUICode

```bash
python unity_batch.py -p sgi_client/client -m ClaudeEditorHelper.AutoGenUICode --extra-args "-prefab Assets/Res/UI/WndForm/WndForm_XXX.prefab"
```

產出：InitComp.cs + UIEvent.cs

### 元件組裝 Stack（Phase 2A 實測確認）

> **關鍵原則**：每個 UI 類型有固定的元件 stack。缺少任何一個 → Unity Console 出現 "has possibly missing Required Components!" 警告。
> **GUID 為專案專屬**：每個 Unity 專案的 .cs.meta GUID 不同，見 `unity-prefab-component-guids` atom。

#### Root（WndForm）

| # | 元件 | 備註 |
|---|------|------|
| 1 | RectTransform | Anchor: stretch, Pivot: 0.5/0.5 |
| 2 | Canvas | RenderMode: 2 (ScreenSpaceCamera) |
| 3 | GraphicRaycaster | 使用 MonoBehaviour 114 |
| 4 | CanvasGroup | Alpha: 1, Interactable: true |
| 5 | UIPerformance | 使用 MonoBehaviour 114 |
| 6 | ILUIWnd | 包含 RefDb + _uiWndID |

#### UIButtonCustom（普通按鈕）

| # | 元件 | YAML Type | 備註 |
|---|------|-----------|------|
| 1 | RectTransform | !u!224 | |
| 2 | CanvasRenderer | !u!222 | |
| 3 | **EmptyGraphic** | !u!114 | guid: `2db8e84a`... — 透明 Graphic，僅供 Raycast 點擊區域 |
| 4 | **UIButtonCustom** | !u!114 | guid: `89779232`... — `[RequireComponent(typeof(EmptyGraphic))]` |
| 5 | CanvasGroup | !u!225 | |

- UIButtonCustom 的 `[RequireComponent]` 指定 **EmptyGraphic**，不可用 Unity Image 替代
- EmptyGraphic 來源：`Assets/MainScripts/Framework/UIComponent/EmptyGraphic.cs`

#### Toggle 按鈕（帶狀態切換）

| # | 元件 | YAML Type | 備註 |
|---|------|-----------|------|
| 1 | RectTransform | !u!224 | |
| 2 | CanvasRenderer | !u!222 | |
| 3 | EmptyGraphic | !u!114 | guid: `2db8e84a`... |
| 4 | **UJToggle** | !u!114 | guid: `37cc876e`... — Toggle 子類 |
| 5 | UIButtonCustom | !u!114 | guid: `89779232`... |
| 6 | CanvasGroup | !u!225 | |

- UJToggle 繼承 Unity Toggle，來源：`Assets/MainScripts/Game/UIComponent/UJToggle.cs`
- 僅用於需要 toggle 狀態的按鈕（如 tab 頁籤切換）

#### Scroller（捲動列表）

| # | 元件 | YAML Type | 備註 |
|---|------|-----------|------|
| 1 | RectTransform | !u!224 | |
| 2 | **ScrollRect** | !u!114 | guid: `1aa08ab6`... — m_Content/m_Viewport 設 {fileID: 0} |
| 3 | **EnhancedScroller** | !u!114 | guid: `9c1b74f9`... — `[RequireComponent(typeof(ScrollRect))]` |
| 4 | CanvasRenderer | !u!222 | |
| 5 | **Image** | !u!114 | guid: `fe87c0e1`... — 為 Mask 提供 Graphic |
| 6 | **Mask** | !u!114 | guid: `31a19414`... — m_ShowMaskGraphic: 0 |
| 7 | ILUIScrollerController | !u!114 | guid: `38afe61a`... |

- ScrollRect 設定：m_Horizontal: 0, m_Vertical: 1, m_MovementType: 2

#### Widget Cell（Scroller 的列表項目）

| # | 元件 | YAML Type | 備註 |
|---|------|-----------|------|
| 1 | RectTransform | !u!224 | |
| 2 | EnhancedScrollerCellView | !u!114 | guid: `1f75717e`... — Cell 基底類（可選，部分 cell 有） |
| 3 | **ILUIWidget** | !u!114 | guid: `c4d39f5c`... — 含 RefDb |
| 4 | **ILUIScrollerView** | !u!114 | guid: `c03f8bb1`... |

- 最小 cell 只需 RectTransform + ILUIWidget + ILUIScrollerView（3 元件）
- EnhancedScrollerCellView 為第三方插件基底，部分舊 cell 有掛載

#### Text

| # | 元件 | YAML Type | 備註 |
|---|------|-----------|------|
| 1 | RectTransform | !u!224 | |
| 2 | CanvasRenderer | !u!222 | |
| 3 | Text | !u!114 | guid: `5f7201a1`... |

### 診斷流程：Console 警告排查

**"has possibly missing Required Components!"**：
1. 從警告找 GameObject 名稱
2. 在 prefab YAML 找該 GO 的 `m_Component` 列表
3. 查 MonoBehaviour GUID → 找 .cs 源碼
4. `grep -n "RequireComponent"` → 找缺少的元件 → 加入 YAML

### 注意事項

- RefDb 的 _typeName 要與元件的 C# class name 一致
- EmptyGraphic 序列化格式比 Image 簡單（無 m_Sprite、m_Type 等欄位）
- generate-ui-prefab 工具已修正（2026-03-25）：UIButtonCustom 用 EmptyGraphic + CanvasGroup，Scroller 含完整 7 元件 stack
- 測試/練習用的 prefab 不上傳 SVN

## 行動

- 建立 prefab → 依照 5 步驟 SOP 執行
- Console 有 "missing Required Components" → 按診斷流程排查
- 不確定元件 stack → 查本 atom 對應 UI 類型表

## 演化日誌

| 日期 | 變更 | 來源 |
|------|------|------|
| 2026-03-24 | 初始建立（claude-native 格式） | Phase 2A 實測 |
| 2026-03-25 | 格式修正：claude-native → 原子記憶標準格式 | memory-health 診斷 |
| 2026-03-25 | 工具修正確認 + Widget Cell stack + EnhancedScrollerCellView GUID | Phase 2B/C/D |
