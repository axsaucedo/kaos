package adapters

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

func TestIssuerConsistencyProjectorConditions(t *testing.T) {
	for _, test := range []struct {
		name       string
		discovered func(string) string
		status     metav1.ConditionStatus
		reason     string
	}{
		{name: "matching issuer", discovered: func(configured string) string { return configured }, status: metav1.ConditionFalse, reason: "IssuerConsistent"},
		{name: "mismatched issuer", discovered: func(string) string { return "http://broker-wrong:8000" }, status: metav1.ConditionTrue, reason: "IssuerMismatch"},
	} {
		t.Run(test.name, func(t *testing.T) {
			var server *httptest.Server
			server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/.well-known/openid-configuration" {
					http.NotFound(w, r)
					return
				}
				_, _ = fmt.Fprintf(w, `{"issuer":%q}`, test.discovered(server.URL))
			}))
			defer server.Close()

			scheme := newTestScheme(t)
			agent := &kaosv1alpha1.Agent{ObjectMeta: metav1.ObjectMeta{Namespace: "demo", Name: "researcher", Generation: 3}}
			client := fake.NewClientBuilder().WithScheme(scheme).WithStatusSubresource(agent).WithObjects(agent).Build()
			projector := &IssuerConsistencyProjector{Client: client, HTTPClient: server.Client(), Issuer: server.URL}
			if err := projector.Apply(context.Background(), projection.DesiredState{}); err != nil {
				t.Fatalf("Apply: %v", err)
			}

			updated := &kaosv1alpha1.Agent{}
			if err := client.Get(context.Background(), types.NamespacedName{Namespace: "demo", Name: "researcher"}, updated); err != nil {
				t.Fatalf("get Agent: %v", err)
			}
			condition := meta.FindStatusCondition(updated.Status.Conditions, identityIssuerDegradedCondition)
			if condition == nil || condition.Status != test.status || condition.Reason != test.reason || condition.ObservedGeneration != 3 {
				t.Fatalf("condition = %#v", condition)
			}
		})
	}
}
