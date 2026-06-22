package identity

import (
	"testing"
	"time"
)

func ts(sec int64) time.Time { return time.Unix(sec, 0).UTC() }

func TestDetectConflictNoExplicitID(t *testing.T) {
	self := Holder{Namespace: "a", Name: "x"}
	if _, conflict := DetectConflict(self, []Holder{self}); conflict {
		t.Errorf("resource without explicit id must never conflict")
	}
}

func TestDetectConflictOldestWins(t *testing.T) {
	older := Holder{Namespace: "a", Name: "older", SecurityID: "shared", CreationTimestamp: ts(100)}
	newer := Holder{Namespace: "b", Name: "newer", SecurityID: "shared", CreationTimestamp: ts(200)}
	candidates := []Holder{newer, older}

	if winner, conflict := DetectConflict(older, candidates); conflict {
		t.Errorf("older holder should own the id, got conflict with winner %+v", winner)
	}
	winner, conflict := DetectConflict(newer, candidates)
	if !conflict {
		t.Fatalf("newer holder should lose the shared id")
	}
	if winner.Name != "older" {
		t.Errorf("winner = %q, want older", winner.Name)
	}
}

func TestDetectConflictTiebreakByNamespaceThenName(t *testing.T) {
	a := Holder{Namespace: "ns-a", Name: "n2", SecurityID: "s", CreationTimestamp: ts(50)}
	b := Holder{Namespace: "ns-b", Name: "n1", SecurityID: "s", CreationTimestamp: ts(50)}
	candidates := []Holder{b, a}
	winner, _ := LegitimateHolder("s", candidates)
	if winner.Namespace != "ns-a" {
		t.Errorf("equal timestamps should tiebreak on namespace: winner=%+v", winner)
	}
}

func TestDetectConflictDistinctIDsNoConflict(t *testing.T) {
	a := Holder{Namespace: "a", Name: "x", SecurityID: "one", CreationTimestamp: ts(10)}
	b := Holder{Namespace: "b", Name: "y", SecurityID: "two", CreationTimestamp: ts(20)}
	candidates := []Holder{a, b}
	if _, c := DetectConflict(a, candidates); c {
		t.Errorf("distinct ids must not conflict (a)")
	}
	if _, c := DetectConflict(b, candidates); c {
		t.Errorf("distinct ids must not conflict (b)")
	}
}

func TestDetectConflictAdoptionAfterHolderGone(t *testing.T) {
	// After the older holder is deleted, only the newer remains in candidates
	// and becomes the legitimate holder (adoption).
	newer := Holder{Namespace: "b", Name: "newer", SecurityID: "shared", CreationTimestamp: ts(200)}
	if _, conflict := DetectConflict(newer, []Holder{newer}); conflict {
		t.Errorf("sole remaining holder should adopt the id, got conflict")
	}
}
