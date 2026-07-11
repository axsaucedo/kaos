package adapters

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	kaosv1alpha1 "github.com/axsaucedo/kaos/operator/api/v1alpha1"
	"github.com/axsaucedo/kaos/operator/internal/authz"
	"github.com/axsaucedo/kaos/operator/internal/projection"
)

const identityIssuerDegradedCondition = "IdentityIssuerDegraded"

// IssuerConsistencyProjector checks that AIB advertises the configured issuer
// and records the result on every Agent without blocking the remaining sinks.
type IssuerConsistencyProjector struct {
	Client     client.Client
	HTTPClient *http.Client
	Issuer     string
	Namespaces []string
}

func (p *IssuerConsistencyProjector) Apply(ctx context.Context, _ projection.DesiredState) error {
	configured := strings.TrimSpace(p.Issuer)
	discovered, checkErr := authz.DiscoverIssuer(ctx, p.HTTPClient, configured)
	condition := metav1.Condition{
		Type:    identityIssuerDegradedCondition,
		Status:  metav1.ConditionFalse,
		Reason:  "IssuerConsistent",
		Message: fmt.Sprintf("Configured issuer %q matches AIB discovery", configured),
	}
	if checkErr != nil {
		condition.Status = metav1.ConditionTrue
		condition.Reason = "IssuerDiscoveryFailed"
		condition.Message = checkErr.Error()
		log.FromContext(ctx).Error(checkErr, "unable to verify AIB issuer consistency", "configuredIssuer", configured)
	} else if discovered != configured {
		condition.Status = metav1.ConditionTrue
		condition.Reason = "IssuerMismatch"
		condition.Message = fmt.Sprintf("Configured issuer %q does not match AIB discovery issuer %q", configured, discovered)
		log.FromContext(ctx).Error(fmt.Errorf("%s", condition.Message), "AIB issuer mismatch", "configuredIssuer", configured, "discoveredIssuer", discovered)
	}

	namespaces := p.Namespaces
	if len(namespaces) == 0 {
		namespaces = []string{""}
	}
	for _, namespace := range namespaces {
		agents := &kaosv1alpha1.AgentList{}
		var options []client.ListOption
		if namespace != "" {
			options = append(options, client.InNamespace(namespace))
		}
		if err := p.Client.List(ctx, agents, options...); err != nil {
			return fmt.Errorf("listing Agents for issuer condition: %w", err)
		}
		for i := range agents.Items {
			agent := &agents.Items[i]
			original := agent.DeepCopy()
			condition.ObservedGeneration = agent.Generation
			if !meta.SetStatusCondition(&agent.Status.Conditions, condition) {
				continue
			}
			if err := p.Client.Status().Patch(ctx, agent, client.MergeFrom(original)); err != nil {
				return fmt.Errorf("updating Agent %s/%s issuer condition: %w", agent.Namespace, agent.Name, err)
			}
		}
	}
	return nil
}
