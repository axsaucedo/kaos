// Package util provides shared utilities for controllers
package util

import (
	"encoding/json"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/util/strategicpatch"
)

// MergePodSpec merges a patch PodSpec into a base PodSpec using strategic merge patch.
// This allows users to override specific fields (like resources, replicas via podSpec)
// while preserving the base configuration.
func MergePodSpec(base, patch corev1.PodSpec) (corev1.PodSpec, error) {
	baseJSON, err := json.Marshal(base)
	if err != nil {
		return base, err
	}

	patchJSON, err := json.Marshal(patch)
	if err != nil {
		return base, err
	}

	mergedJSON, err := strategicpatch.StrategicMergePatch(baseJSON, patchJSON, corev1.PodSpec{})
	if err != nil {
		return base, err
	}

	var merged corev1.PodSpec
	if err := json.Unmarshal(mergedJSON, &merged); err != nil {
		return base, err
	}

	return merged, nil
}
