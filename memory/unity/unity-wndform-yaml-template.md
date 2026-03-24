---
name: unity-wndform-yaml-template
description: WndForm prefab YAML root structure template for programmatic creation
type: reference
---

## WndForm Prefab Root Structure

> 最小 WndForm 4 元件：RectTransform + Canvas + GraphicRaycaster + CanvasGroup
> 標準 WndForm 6 元件：上述 + UIPerformance + ILUIWnd（含 RefDb）

### Root GameObject 模板

```yaml
--- !u!1 &{GO_ID}
GameObject:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  serializedVersion: 6
  m_Component:
  - component: {fileID: {RECT_ID}}      # RectTransform
  - component: {fileID: {CANVAS_ID}}     # Canvas
  - component: {fileID: {RAYCASTER_ID}} # GraphicRaycaster
  - component: {fileID: {CG_ID}}        # CanvasGroup
  - component: {fileID: {PERF_ID}}      # UIPerformance (optional)
  - component: {fileID: {WNDID}}        # ILUIWnd (optional)
  m_Layer: 5                             # UI layer
  m_Name: WndForm_XXX
  m_TagString: Untagged
  m_Icon: {fileID: 0}
  m_NavMeshLayer: 0
  m_StaticEditorFlags: 0
  m_IsActive: 1
```

### RectTransform（全畫面拉伸）

```yaml
--- !u!224 &{RECT_ID}
RectTransform:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: {GO_ID}}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_ConstrainProportionsScale: 0
  m_Children: [{fileID: {CHILD_RECT_ID}}]  # child RectTransform IDs
  m_Father: {fileID: 0}
  m_RootOrder: 0
  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}
  m_AnchorMin: {x: 0, y: 0}
  m_AnchorMax: {x: 1, y: 1}
  m_AnchoredPosition: {x: 0, y: 0}
  m_SizeDelta: {x: 0, y: 0}
  m_Pivot: {x: 0.5, y: 0.5}
```

### Canvas

```yaml
--- !u!223 &{CANVAS_ID}
Canvas:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: {GO_ID}}
  m_Enabled: 1
  serializedVersion: 3
  m_RenderMode: 2
  m_Camera: {fileID: 0}
  m_PlaneDistance: 100
  m_PixelPerfect: 0
  m_ReceivesEvents: 1
  m_OverrideSorting: 0
  m_OverridePixelPerfect: 0
  m_SortingBucketNormalizedSize: 0
  m_VertexColorAlwaysGammaSpace: 0
  m_AdditionalShaderChannelsFlag: 25
  m_UpdateRectTransformForStandalone: 0
  m_SortingLayerID: 0
  m_SortingOrder: 0
  m_TargetDisplay: 0
```

### ILUIWnd RefDb 結構

```yaml
--- !u!114 &{WNDID}
MonoBehaviour:
  m_Script: {fileID: 11500000, guid: 92d84008b0651f44b82b6792322b6551, type: 3}
  _refDb:
    _objects:
    - _key: Load_Title
      _typeName: Text
      Objs:
      - {fileID: {TEXT_COMP_ID}}
    - _key: Confirm
      _typeName: UIButtonCustom
      Objs:
      - {fileID: {BTN_COMP_ID}}
    _fieldDb:
      _fields: []
    _uiWndID: WndForm_XXX
    DisableInvokeUpdate: 0
    UsingFrameUpdate: 1
    UpdateFrameRate: 0
    UpdateInterval: 1
```

### Scroller 3-Component Stack

Scroller 需要 3 個 Component 掛在同一個 GameObject 上：
1. EnhancedScroller (GUID: 9c1b74f910281224a8cae6d8e4fc1f43)
2. ILUIScrollerController (GUID: 38afe61accd76f840899fdc078e09ef9) — 設 _scrollClassName
3. ILUIScrollerView 掛在 Cell template GameObject 上 (GUID: c03f8bb183d633a49986b0e8525f3c4e)

### AutoGenUICode 生成邏輯

- 無 MenuItem，從 Inspector 按鈕觸發
- 入口：`new AutoGenUICode(wnd).AutoGenCSharpCode()`
- 讀 RefDb._objects → 產生 InitComp.cs + UIEvent.cs
- 模板：`Assets/MainScripts/ScriptGenerator/Editor/ILScript/UIFramework/UIWndInitComp.cs.txt`
- Marker 取代：`//#COMPONENT_VAR#` 和 `//#INIT_COMPONENT#`
