---
name: unity-prefab-component-guids
description: SGI Client 專案專屬的 UI component script GUID 對照表（不適用其他 Unity 專案）
type: reference
---

## UI Component Script GUIDs (SGI Client, Unity 2022.3.62f2)

> **專案專屬**：這些 GUID 來自 SGI Client 專案的 .cs.meta / .dll.meta，不同 Unity 專案的 GUID 完全不同。
> 用途：程式化建立/修改 .prefab YAML 時，MonoBehaviour 的 m_Script 欄位需要正確的 GUID。

### 核心 UI 框架

| Component | GUID | Source |
|-----------|------|--------|
| ILUIWnd | `92d84008b0651f44b82b6792322b6551` | `Assets/ILRuntimeScripts/Core/UI/ILUIWnd.cs` |
| ILUIWidget | `c4d39f5c5f9f8b544915a8e00f055d80` | `Assets/ILRuntimeScripts/Core/UI/ILUIWidget.cs` |
| ILUIScrollerController | `38afe61accd76f840899fdc078e09ef9` | `Assets/ILRuntimeScripts/Core/UI/ILUIScrollerController.cs` |
| ILUIScrollerView | `c03f8bb183d633a49986b0e8525f3c4e` | `Assets/ILRuntimeScripts/Core/UI/ILUIScrollerView.cs` |
| UIPerformance | `e462dac500424c5439978c56da2c7c27` | `Assets/MainScripts/.../UIPerformance.cs` |
| UIButtonCustom | `89779232b761c444897d167013b46555` | `Assets/MainScripts/.../DoozyExtension/Component/UIButtonCustom.cs` |
| UIButton (Doozy) | `7d12bfc32d0d797428cf0191288caabd` | `Assets/MainScripts/.../Doozy/Engine/UI/UIButton/UIButton.cs` |
| EmptyGraphic | `2db8e84a7ad1bcd478233499422f2496` | `Assets/MainScripts/Framework/UIComponent/EmptyGraphic.cs` |
| UJToggle | `37cc876e277f93d4685c49829def45af` | `Assets/MainScripts/Game/UIComponent/UJToggle.cs` |
| Mask | `31a19414c41e5ae4aae2af33fee712f6` | Unity 內建 `UnityEngine.UI.Mask` |

### RequireComponent 依賴（實測確認）

| Component | Requires | 備註 |
|-----------|----------|------|
| UIButtonCustom | EmptyGraphic + RectTransform | 來源: UIButtonCustom.cs line 30-31 |
| EnhancedScroller | ScrollRect | ScrollRect + CanvasRenderer + Image + Mask 完整 stack |
| UJToggle | Graphic (any) | Toggle 子類，需 targetGraphic；僅 toggle 按鈕用 |

### Unity 內建 UI (from UnityEngine.UI DLL)

| Component | GUID | Note |
|-----------|------|------|
| GraphicRaycaster | `dc42784cf147c0c48a680349fa168899` | Canvas 必備 |
| Image | `fe87c0e1cc204ed48ad3b37840f39efc` | 圖片/按鈕背景 |
| RawImage | `1344c3c82d62a2a41a3576d8abb8e3ea` | 原始圖片 |
| Text | `5f7201a12d95ffc409449d95f23cf332` | 文字元件 |
| Button | `4e29b1a8efbd4b44bb3f3716e73f07ff` | Unity 原生按鈕 |
| ScrollRect | `1aa08ab6e0800fa44ae55d278d1423e3` | 捲動區域 |
| ContentSizeFitter | `3245ec927659c4140ac4f8d17403cc18` | 內容尺寸適配 |
| VerticalLayoutGroup | `30649d3a9faa99c48a7b1166b86bf2a0` | 垂直排版 |
| HorizontalLayoutGroup | `59f8146938fff824cb5fd77236b75775` | 水平排版 |
| LayoutElement | `306cc8c2b49d7114eaa3623786fc2126` | 排版元素 |

### 第三方

| Component | GUID | Note |
|-----------|------|------|
| EnhancedScroller | `9c1b74f910281224a8cae6d8e4fc1f43` | `EnhancedScroller v2/Plugins/` |
| EnhancedScrollerCellView | `1f75717e94199704f82f26fcf6953e84` | Cell 基底類，Widget cell root 掛載 |

### MonoBehaviour m_Script 格式

所有 MonoBehaviour 的 m_Script 固定格式：
```yaml
m_Script: {fileID: 11500000, guid: <GUID>, type: 3}
```
- fileID 固定 `11500000`
- type 固定 `3`（MonoScript 參照）

### 元件序列化範本（最小欄位集）

**EmptyGraphic**（按鈕用，透明 Graphic 僅供 Raycast）：
```yaml
--- !u!114 &<fileID>
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: <parent_GO>}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: 2db8e84a7ad1bcd478233499422f2496, type: 3}
  m_Name:
  m_EditorClassIdentifier:
  m_Material: {fileID: 0}
  m_Color: {r: 1, g: 1, b: 1, a: 1}
  m_RaycastTarget: 1
  m_RaycastPadding: {x: 0, y: 0, z: 0, w: 0}
```

**ScrollRect**（Scroller 用，vertical-only 預設）：
```yaml
--- !u!114 &<fileID>
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: <parent_GO>}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: 1aa08ab6e0800fa44ae55d278d1423e3, type: 3}
  m_Name:
  m_EditorClassIdentifier:
  m_Content: {fileID: 0}
  m_Horizontal: 0
  m_Vertical: 1
  m_MovementType: 2
  m_Elasticity: 0.1
  m_Inertia: 1
  m_DecelerationRate: 0.135
  m_ScrollSensitivity: 1
  m_Viewport: {fileID: 0}
  m_HorizontalScrollbar: {fileID: 0}
  m_VerticalScrollbar: {fileID: 0}
  m_HorizontalScrollbarVisibility: 0
  m_VerticalScrollbarVisibility: 0
  m_HorizontalScrollbarSpacing: 0
  m_VerticalScrollbarSpacing: 0
  m_OnValueChanged:
    m_PersistentCalls:
      m_Calls: []
```

**Mask**（Scroller 遮罩用）：
```yaml
--- !u!114 &<fileID>
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: <parent_GO>}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: 31a19414c41e5ae4aae2af33fee712f6, type: 3}
  m_Name:
  m_EditorClassIdentifier:
  m_ShowMaskGraphic: 0
```

**Image**（完整序列化，Scroller 的 Mask Graphic 或一般圖片用）：
```yaml
--- !u!114 &<fileID>
MonoBehaviour:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: <parent_GO>}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: fe87c0e1cc204ed48ad3b37840f39efc, type: 3}
  m_Name:
  m_EditorClassIdentifier:
  m_Material: {fileID: 0}
  m_Color: {r: 1, g: 1, b: 1, a: 1}
  m_RaycastTarget: 1
  m_RaycastPadding: {x: 0, y: 0, z: 0, w: 0}
  m_Maskable: 1
  m_OnCullStateChanged:
    m_PersistentCalls:
      m_Calls: []
  m_Sprite: {fileID: 0}
  m_Type: 0
  m_PreserveAspect: 0
  m_FillCenter: 1
  m_FillMethod: 4
  m_FillAmount: 1
  m_FillClockwise: 1
  m_FillOrigin: 0
  m_UseSpriteMesh: 0
  m_PixelsPerUnitMultiplier: 1
```

### Unity YAML Type IDs (built-in)

| Type | ClassID | Tag |
|------|---------|-----|
| GameObject | 1 | `!u!1` |
| Transform | 4 | `!u!4` |
| RectTransform | 224 | `!u!224` |
| Canvas | 223 | `!u!223` |
| CanvasGroup | 225 | `!u!225` |
| CanvasRenderer | 222 | `!u!222` |
| Animator | 95 | `!u!95` |
| MonoBehaviour | 114 | `!u!114` |
