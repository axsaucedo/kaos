package identity

import (
	"sort"
	"time"
)

// Holder identifies a resource that may claim an explicit security id. The zero
// CreationTimestamp sorts oldest, so callers should always populate it from the
// resource metadata.
type Holder struct {
	Namespace         string
	Name              string
	SecurityID        string
	CreationTimestamp time.Time
}

// sameResource reports whether two holders refer to the same object.
func (h Holder) sameResource(other Holder) bool {
	return h.Namespace == other.Namespace && h.Name == other.Name
}

// LegitimateHolder returns the resource that legitimately owns a shared explicit
// security id among candidates that declare the same id. Ownership is the
// oldest creationTimestamp, with namespace then name as deterministic
// tiebreaks so every controller converges on the same winner regardless of
// reconcile order. Candidates with a different or empty SecurityID are ignored.
// Returns false when no candidate declares securityID.
func LegitimateHolder(securityID string, candidates []Holder) (Holder, bool) {
	if securityID == "" {
		return Holder{}, false
	}
	var matching []Holder
	for _, c := range candidates {
		if c.SecurityID == securityID {
			matching = append(matching, c)
		}
	}
	if len(matching) == 0 {
		return Holder{}, false
	}
	sort.SliceStable(matching, func(i, j int) bool {
		a, b := matching[i], matching[j]
		if !a.CreationTimestamp.Equal(b.CreationTimestamp) {
			return a.CreationTimestamp.Before(b.CreationTimestamp)
		}
		if a.Namespace != b.Namespace {
			return a.Namespace < b.Namespace
		}
		return a.Name < b.Name
	})
	return matching[0], true
}

// DetectConflict reports whether self is NOT the legitimate holder of its
// explicit security id among candidates (which must include self). It returns
// the winning holder for status messaging and true when self loses the id to
// another resource. When self has no explicit id, or is itself the legitimate
// holder, conflict is false.
func DetectConflict(self Holder, candidates []Holder) (winner Holder, conflict bool) {
	if self.SecurityID == "" {
		return Holder{}, false
	}
	holder, ok := LegitimateHolder(self.SecurityID, candidates)
	if !ok || holder.sameResource(self) {
		return self, false
	}
	return holder, true
}
