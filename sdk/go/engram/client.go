// Package engram provides a Go client for the Engram AI Memory API.
//
// Usage:
//
//	client := engram.New("http://localhost:8000",
//	    engram.WithAPIKey("your-key"),
//	)
//	mem, err := client.Memories.Create(ctx, "ws-id", engram.MemoryCreate{
//	    Content: "Kubernetes liveness probes restart containers.",
//	    Type:    "note",
//	    Tags:    []string{"k8s"},
//	})
package engram

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// ─── Client ────────────────────────────────────────────────────────────────

// Client is the main Engram API client.
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client

	Workspaces  *WorkspacesService
	Memories    *MemoriesService
	Search      *SearchService
	Agents      *AgentsService
	Workflows   *WorkflowsService
	Marketplace *MarketplaceService
}

// Option is a functional option for Client.
type Option func(*Client)

// WithAPIKey sets the API key.
func WithAPIKey(key string) Option {
	return func(c *Client) { c.apiKey = key }
}

// WithHTTPClient sets a custom http.Client.
func WithHTTPClient(hc *http.Client) Option {
	return func(c *Client) { c.httpClient = hc }
}

// New creates a new Engram client.
func New(baseURL string, opts ...Option) *Client {
	baseURL = strings.TrimRight(baseURL, "/")
	c := &Client{
		baseURL:    baseURL,
		httpClient: &http.Client{Timeout: 60 * time.Second},
	}
	for _, o := range opts {
		o(c)
	}
	c.Workspaces = &WorkspacesService{c}
	c.Memories = &MemoriesService{c}
	c.Search = &SearchService{c}
	c.Agents = &AgentsService{c}
	c.Workflows = &WorkflowsService{c}
	c.Marketplace = &MarketplaceService{c}
	return c
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var bodyReader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal: %w", err)
		}
		bodyReader = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("X-Api-Key", c.apiKey)
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("http: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == 204 {
		return nil
	}
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		var errBody struct{ Detail any `json:"detail"` }
		_ = json.Unmarshal(data, &errBody)
		return fmt.Errorf("api error %d: %v", resp.StatusCode, errBody.Detail)
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("unmarshal: %w", err)
		}
	}
	return nil
}

// ─── Types ─────────────────────────────────────────────────────────────────

type Workspace struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Slug        string `json:"slug"`
	CreatedAt   string `json:"created_at"`
	MemoryCount int    `json:"memory_count"`
}

type Memory struct {
	ID          string            `json:"id"`
	WorkspaceID string            `json:"workspace_id"`
	Type        string            `json:"type"`
	Title       string            `json:"title"`
	Content     string            `json:"content"`
	Summary     string            `json:"summary"`
	Keywords    []string          `json:"keywords"`
	Tags        []string          `json:"tags"`
	Source      string            `json:"source"`
	Author      string            `json:"author"`
	Importance  float64           `json:"importance"`
	Confidence  float64           `json:"confidence"`
	AccessCount int               `json:"access_count"`
	Archived    bool              `json:"archived"`
	CreatedAt   string            `json:"created_at"`
	UpdatedAt   string            `json:"updated_at"`
	Entities    []map[string]any  `json:"entities"`
}

type MemoryCreate struct {
	Content string   `json:"content"`
	Type    string   `json:"type,omitempty"`
	Title   string   `json:"title,omitempty"`
	Source  string   `json:"source,omitempty"`
	Author  string   `json:"author,omitempty"`
	Tags    []string `json:"tags,omitempty"`
}

type SearchResult struct {
	MemoryID string  `json:"memory_id"`
	Title    string  `json:"title"`
	Content  string  `json:"content"`
	Score    float64 `json:"score"`
	Type     string  `json:"type"`
}

type AgentRun struct {
	ID          string         `json:"id"`
	WorkspaceID string         `json:"workspace_id"`
	Goal        string         `json:"goal"`
	Status      string         `json:"status"`
	Conclusion  string         `json:"conclusion"`
	StartedAt   string         `json:"started_at"`
	FinishedAt  string         `json:"finished_at"`
	Messages    []AgentMessage `json:"messages,omitempty"`
}

type AgentMessage struct {
	Seq       int    `json:"seq"`
	Sender    string `json:"sender"`
	Recipient string `json:"recipient"`
	Kind      string `json:"kind"`
	Content   string `json:"content"`
	CreatedAt string `json:"created_at"`
}

type Workflow struct {
	ID           string         `json:"id"`
	WorkspaceID  string         `json:"workspace_id"`
	Name         string         `json:"name"`
	Description  string         `json:"description"`
	TriggerEvent string         `json:"trigger_event"`
	Steps        []map[string]any `json:"steps"`
	Enabled      bool           `json:"enabled"`
	CreatedAt    string         `json:"created_at"`
	UpdatedAt    string         `json:"updated_at"`
}

type Plugin struct {
	ID            string `json:"id"`
	Slug          string `json:"slug"`
	Name          string `json:"name"`
	Kind          string `json:"kind"`
	Description   string `json:"description"`
	Author        string `json:"author"`
	FirstParty    bool   `json:"first_party"`
	LatestVersion string `json:"latest_version"`
}

// ─── Services ──────────────────────────────────────────────────────────────

// WorkspacesService handles workspace operations.
type WorkspacesService struct{ c *Client }

func (s *WorkspacesService) List(ctx context.Context) ([]Workspace, error) {
	var r struct{ Items []Workspace `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, "/v1/workspaces", nil, &r)
}

func (s *WorkspacesService) Create(ctx context.Context, name, slug string) (*Workspace, error) {
	var ws Workspace
	return &ws, s.c.do(ctx, http.MethodPost, "/v1/workspaces", map[string]string{"name": name, "slug": slug}, &ws)
}

// MemoriesService handles memory CRUD.
type MemoriesService struct{ c *Client }

func (s *MemoriesService) List(ctx context.Context, wsID string, limit int) ([]Memory, error) {
	p := url.Values{}
	if limit > 0 {
		p.Set("limit", fmt.Sprintf("%d", limit))
	}
	var r struct{ Items []Memory `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, fmt.Sprintf("/v1/workspaces/%s/memories?%s", wsID, p.Encode()), nil, &r)
}

func (s *MemoriesService) Create(ctx context.Context, wsID string, body MemoryCreate) (*Memory, error) {
	var mem Memory
	return &mem, s.c.do(ctx, http.MethodPost, fmt.Sprintf("/v1/workspaces/%s/memories", wsID), body, &mem)
}

func (s *MemoriesService) Get(ctx context.Context, memID string) (*Memory, error) {
	var mem Memory
	return &mem, s.c.do(ctx, http.MethodGet, fmt.Sprintf("/v1/memories/%s", memID), nil, &mem)
}

func (s *MemoriesService) Delete(ctx context.Context, memID string) error {
	return s.c.do(ctx, http.MethodDelete, fmt.Sprintf("/v1/memories/%s", memID), nil, nil)
}

func (s *MemoriesService) Related(ctx context.Context, memID string) ([]map[string]any, error) {
	var r struct{ Items []map[string]any `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, fmt.Sprintf("/v1/memories/%s/related", memID), nil, &r)
}

// SearchService handles search and RAG context.
type SearchService struct{ c *Client }

func (s *SearchService) Search(ctx context.Context, wsID, query string, limit int) ([]SearchResult, error) {
	body := map[string]any{"query": query, "limit": limit}
	var r struct{ Results []SearchResult `json:"results"` }
	return r.Results, s.c.do(ctx, http.MethodPost, fmt.Sprintf("/v1/workspaces/%s/search", wsID), body, &r)
}

func (s *SearchService) Context(ctx context.Context, wsID, query string, maxTokens int) (map[string]any, error) {
	body := map[string]any{"query": query, "max_tokens": maxTokens}
	var r map[string]any
	return r, s.c.do(ctx, http.MethodPost, fmt.Sprintf("/v1/workspaces/%s/context", wsID), body, &r)
}

// AgentsService handles multi-agent orchestration.
type AgentsService struct{ c *Client }

func (s *AgentsService) Run(ctx context.Context, wsID, goal string, team []string) (*AgentRun, error) {
	body := map[string]any{"goal": goal}
	if len(team) > 0 {
		body["team"] = team
	}
	var run AgentRun
	return &run, s.c.do(ctx, http.MethodPost, fmt.Sprintf("/v1/workspaces/%s/agents/run", wsID), body, &run)
}

func (s *AgentsService) List(ctx context.Context, wsID string) ([]AgentRun, error) {
	var r struct{ Items []AgentRun `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, fmt.Sprintf("/v1/workspaces/%s/agents/runs", wsID), nil, &r)
}

// WorkflowsService handles workflow operations.
type WorkflowsService struct{ c *Client }

func (s *WorkflowsService) List(ctx context.Context, wsID string) ([]Workflow, error) {
	var r struct{ Items []Workflow `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, fmt.Sprintf("/v1/workspaces/%s/workflows", wsID), nil, &r)
}

func (s *WorkflowsService) Trigger(ctx context.Context, wsID, wfID string, variables map[string]any) (map[string]any, error) {
	var r map[string]any
	return r, s.c.do(ctx, http.MethodPost, fmt.Sprintf("/v1/workspaces/%s/workflows/%s/trigger", wsID, wfID), map[string]any{"variables": variables}, &r)
}

// MarketplaceService handles the plugin catalog.
type MarketplaceService struct{ c *Client }

func (s *MarketplaceService) List(ctx context.Context) ([]Plugin, error) {
	var r struct{ Items []Plugin `json:"items"` }
	return r.Items, s.c.do(ctx, http.MethodGet, "/v1/catalog", nil, &r)
}

func (s *MarketplaceService) Install(ctx context.Context, wsID, slug, version string) (map[string]any, error) {
	var r map[string]any
	return r, s.c.do(ctx, http.MethodPost,
		fmt.Sprintf("/v1/workspaces/%s/plugins/%s/install", wsID, slug),
		map[string]string{"version": version}, &r)
}
