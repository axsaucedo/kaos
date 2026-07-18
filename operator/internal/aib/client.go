// Package aib is a thin idempotent client over the AIB admin REST API used by
// the reconcile loop. Pre-authentication is plain-header based: the configured
// principal is sent on every request via the configured header. Transient
// failures (connection errors and 5xx) are retried with bounded exponential
// backoff; non-transient 4xx responses surface immediately.
package aib

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/hashicorp/go-retryablehttp"
)

var retryableStatus = map[int]bool{500: true, 502: true, 503: true, 504: true}

// Client is an idempotent client for the AIB admin API.
type Client struct {
	baseURL         string
	principal       string
	principalHeader string
	http            *retryablehttp.Client
}

// retryPolicy retries connection errors and the transient 5xx statuses, leaving
// 4xx and the remaining 5xx for the caller to interpret.
func retryPolicy(ctx context.Context, resp *http.Response, err error) (bool, error) {
	if ctx.Err() != nil {
		return false, ctx.Err()
	}
	if err != nil {
		return true, nil
	}
	return retryableStatus[resp.StatusCode], nil
}

// New returns a Client for the given admin base URL and pre-auth principal.
func New(baseURL, principal, principalHeader string, timeout time.Duration) *Client {
	if principalHeader == "" {
		principalHeader = "X-Remote-User"
	}
	rc := retryablehttp.NewClient()
	rc.HTTPClient.Timeout = timeout
	rc.RetryMax = 3
	rc.RetryWaitMin = 500 * time.Millisecond
	rc.CheckRetry = retryPolicy
	rc.Logger = nil
	return &Client{
		baseURL:         baseURL,
		principal:       principal,
		principalHeader: principalHeader,
		http:            rc,
	}
}

func (c *Client) do(ctx context.Context, method, path string, body any) (*http.Response, []byte, error) {
	var payload []byte
	if body != nil {
		var err error
		if payload, err = json.Marshal(body); err != nil {
			return nil, nil, err
		}
	}
	var reqBody io.Reader
	if payload != nil {
		reqBody = bytes.NewReader(payload)
	}
	req, err := retryablehttp.NewRequestWithContext(ctx, method, c.baseURL+path, reqBody)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set(c.principalHeader, c.principal)
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, nil, err
	}
	data, err := io.ReadAll(resp.Body)
	resp.Body.Close()
	if err != nil {
		return nil, nil, err
	}
	return resp, data, nil
}

// list returns all items in a collection (items envelope or bare list).
func (c *Client) list(ctx context.Context, collection string) ([]map[string]any, error) {
	resp, data, err := c.do(ctx, http.MethodGet, "/"+collection, nil)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode/100 != 2 {
		return nil, fmt.Errorf("list %s: %d %s", collection, resp.StatusCode, string(data))
	}
	var envelope struct {
		Items []map[string]any `json:"items"`
	}
	if err := json.Unmarshal(data, &envelope); err == nil && envelope.Items != nil {
		return envelope.Items, nil
	}
	var bare []map[string]any
	if err := json.Unmarshal(data, &bare); err != nil {
		return nil, err
	}
	return bare, nil
}

// List returns all records in an AIB admin collection.
func (c *Client) List(ctx context.Context, collection string) ([]map[string]any, error) {
	return c.list(ctx, collection)
}

// createOrGet creates a resource and returns its id; if it already exists, the
// collection is scanned for an item whose matchField equals matchValue, making
// the call idempotent across reconcile passes.
func (c *Client) createOrGet(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error) {
	resp, data, err := c.do(ctx, http.MethodPost, "/"+collection, body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode/100 == 2 {
		var created struct {
			ID string `json:"id"`
		}
		if err := json.Unmarshal(data, &created); err != nil {
			return "", err
		}
		return created.ID, nil
	}
	items, err := c.list(ctx, collection)
	if err != nil {
		return "", err
	}
	for _, item := range items {
		if s, _ := item[matchField].(string); s == matchValue {
			if id, _ := item["id"].(string); id != "" {
				return id, nil
			}
		}
	}
	return "", fmt.Errorf("failed to create or find %s %s: %d %s", collection, matchValue, resp.StatusCode, string(data))
}

// CreateOrGet idempotently creates or finds a record in an AIB admin collection.
func (c *Client) CreateOrGet(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error) {
	return c.createOrGet(ctx, collection, matchField, matchValue, body)
}

// Upsert creates a record or replaces the matching record through the admin API.
func (c *Client) Upsert(ctx context.Context, collection, matchField, matchValue string, body map[string]any) (string, error) {
	items, err := c.list(ctx, collection)
	if err != nil {
		return "", err
	}
	for _, item := range items {
		if value, _ := item[matchField].(string); value != matchValue {
			continue
		}
		id, _ := item["id"].(string)
		if id == "" {
			break
		}
		resp, data, err := c.do(ctx, http.MethodPut, "/"+collection+"/"+id, body)
		if err != nil {
			return "", err
		}
		if resp.StatusCode/100 != 2 {
			return "", fmt.Errorf("update %s %s: %d %s", collection, matchValue, resp.StatusCode, string(data))
		}
		return id, nil
	}
	return c.createOrGet(ctx, collection, matchField, matchValue, body)
}

// Update replaces one admin record by id.
func (c *Client) Update(ctx context.Context, collection, id string, body map[string]any) error {
	resp, data, err := c.do(ctx, http.MethodPut, "/"+collection+"/"+id, body)
	if err != nil {
		return err
	}
	if resp.StatusCode/100 != 2 {
		return fmt.Errorf("update %s %s: %d %s", collection, id, resp.StatusCode, string(data))
	}
	return nil
}

// CreateOrGetAgent registers an agent or returns its existing id.
func (c *Client) CreateOrGetAgent(ctx context.Context, externalID string, body map[string]any) (string, error) {
	return c.createOrGet(ctx, "agents", "display_name", externalID, body)
}

// ListAgents returns all registered agents.
func (c *Client) ListAgents(ctx context.Context) ([]map[string]any, error) {
	return c.list(ctx, "agents")
}

// DeleteAgent removes an agent by id. A 404 is treated as success.
func (c *Client) DeleteAgent(ctx context.Context, id string) (bool, error) {
	resp, data, err := c.do(ctx, http.MethodDelete, "/agents/"+id, nil)
	if err != nil {
		return false, err
	}
	if resp.StatusCode == http.StatusNotFound {
		return false, nil
	}
	if resp.StatusCode/100 != 2 {
		return false, fmt.Errorf("delete agent %s: %d %s", id, resp.StatusCode, string(data))
	}
	return true, nil
}

// Credentials is a minted client-credential payload.
type Credentials struct {
	ClientID     string `json:"client_id"`
	ClientSecret string `json:"client_secret"`
}

// MintCredentials mints client credentials for an agent.
func (c *Client) MintCredentials(ctx context.Context, agentID string) (Credentials, error) {
	resp, data, err := c.do(ctx, http.MethodPost, "/agents/"+agentID+"/client-credentials", nil)
	if err != nil {
		return Credentials{}, err
	}
	if resp.StatusCode/100 != 2 {
		return Credentials{}, fmt.Errorf("mint credentials %s: %d %s", agentID, resp.StatusCode, string(data))
	}
	var cred Credentials
	if err := json.Unmarshal(data, &cred); err != nil {
		return Credentials{}, err
	}
	return cred, nil
}
