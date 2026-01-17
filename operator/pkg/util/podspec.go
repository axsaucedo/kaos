// Package util provides shared utilities for controllers
package util

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/util/strategicpatch"
)

// PodSpecHashAnnotation is the annotation key used to store the pod spec hash
const PodSpecHashAnnotation = "kaos.tools/pod-spec-hash"

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

// ComputePodSpecHash computes a SHA256 hash of the pod spec.
// This is used to detect changes that should trigger a rolling update.
func ComputePodSpecHash(spec corev1.PodSpec) string {
	data, err := json.Marshal(spec)
	if err != nil {
		// Fallback to empty hash on error - will always trigger update
		return ""
	}
	hash := sha256.Sum256(data)
	// Use first 16 chars for brevity
	return hex.EncodeToString(hash[:])[:16]
}
