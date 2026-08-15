---
paths:
  - "kaos-ui/src/types/**"
---

# Kubernetes Types Instructions

Guidelines for managing KAOS CRD type definitions in the UI.

## Overview

The KAOS-UI TypeScript types in `kaos-ui/src/types/kubernetes.ts` must stay in sync with the KAOS operator Go types in `operator/api/v1alpha1/`.

Types are focused on CRD definitions only. Canvas/visual-map types live in `src/components/dashboard/visual-map/types.ts`.

## Type Mapping: Go → TypeScript

| Go Type | TypeScript Type |
|---------|-----------------|
| `string` | `string` |
| `[]string` | `string[]` |
| `*string` | `string \| undefined` or optional |
| `map[string]string` | `Record<string, string>` |
| `bool` | `boolean` |
| `int32` | `number` |
| `struct { ... }` | `interface { ... }` |
| `*SomeType` | `SomeType?` |

## Adding New Fields

1. **Update TypeScript interface** in `src/types/kubernetes.ts`
2. **Update Overview component** to display the field
3. **Update Create/Edit dialogs** if field is editable
4. **Add tests** for the new field

## Breaking Changes (Alpha)

The project is in alpha, so breaking changes are permitted:
- `config.env` → `container.env` for all CRDs
- `proxyConfig.model` → `proxyConfig.models` (array)
- `spec.model` added as required field on Agent

## Validation

```bash
cd kaos-ui && npm run build   # Catches type errors
```
