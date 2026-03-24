---
name: unity-prefab-component-guids
description: Unity UI component script GUID registry for programmatic prefab creation (SGI Client project)
type: reference
---

## UI Component Script GUIDs (SGI Client, Unity 2022.3.62f2)

> 用途：程式化建立/修改 .prefab YAML 時，MonoBehaviour 的 m_Script 欄位需要正確的 GUID。
> 來源：從專案 .cs.meta 和 .dll.meta 提取，非硬編碼。

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

### Unity 內建 UI (from UnityEngine.UI DLL)

| Component | GUID | Note |
|-----------|------|------|
| GraphicRaycaster | `dc42784cf147c0c48a680349fa168899` | Canvas 必備 |
| Image | `fe87c0e1cc204ed48ad3b37840f39efc` | 圖片/按鈕背景 |
| RawImage | `1344c3c82d62a2a41a3576d8abb8e3ea` | 原始圖片 |
| Button | `4e29b1a8efbd4b44bb3f3716e73f07ff` | Unity 原生按鈕 |

### 第三方

| Component | GUID | Note |
|-----------|------|------|
| EnhancedScroller | `9c1b74f910281224a8cae6d8e4fc1f43` | `EnhancedScroller v2/Plugins/` |

### MonoBehaviour m_Script 格式

所有 MonoBehaviour 的 m_Script 固定格式：
```yaml
m_Script: {fileID: 11500000, guid: <GUID>, type: 3}
```
- fileID 固定 `11500000`
- type 固定 `3`（MonoScript 參照）

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
