// Package supermemory provides a Go client for the Supermemory Local HTTP API (v4).
//
// Usage:
//
//	client := supermemory.NewClient(supermemory.Config{
//	    BaseURL: "http://localhost:6767",
//	    APIKey:  "your-api-key", // optional
//	})
//
//	// Store a memory
//	resp, err := client.CreateMemory(ctx, "my-project", []supermemory.Memory{
//	    {
//	        Content: "Use hexagonal architecture for clean separation of concerns.",
//	        Metadata: map[string]any{
//	            "type":    "architecture",
//	            "session": "session-123",
//	        },
//	    },
//	})
//
//	// Search
//	results, err := client.SearchMemory(ctx, supermemory.SearchRequest{
//	    Query:        "hexagonal architecture",
//	    ContainerTag: "my-project",
//	    Limit:        10,
//	})
package supermemory

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ─── Config ────────────────────────────────────────────────────────────────

// Config holds client configuration.
type Config struct {
	// BaseURL is the Supermemory Local base URL (default: http://localhost:6767).
	BaseURL string
	// APIKey is the Bearer token for authentication (optional).
	APIKey string
	// Timeout for HTTP requests (default: 10s).
	Timeout time.Duration
}

func (c *Config) defaults() {
	if c.BaseURL == "" {
		c.BaseURL = "http://localhost:6767"
	}
	c.BaseURL = strings.TrimRight(c.BaseURL, "/")
	if c.Timeout == 0 {
		c.Timeout = 10 * time.Second
	}
}

// ─── Models ────────────────────────────────────────────────────────────────

// Memory is a single memory entry to store.
type Memory struct {
	// Content is the main memory text (required, up to 10k chars).
	Content string `json:"content"`
	// IsStatic marks the memory as immutable (no AI mutation).
	IsStatic bool `json:"isStatic,omitempty"`
	// Metadata stores arbitrary fields (session_id, type, tool_name, etc.).
	Metadata map[string]any `json:"metadata,omitempty"`
	// CustomID optionally assigns a deterministic ID to the memory.
	CustomID string `json:"customId,omitempty"`
	// ForgetAfter is an optional expiry time.
	ForgetAfter *time.Time `json:"forgetAfter,omitempty"`
}

// MemoryInfo is a created/retrieved memory entry returned by the API.
type MemoryInfo struct {
	ID        string         `json:"id"`
	Memory    string         `json:"memory"`
	IsStatic  bool           `json:"isStatic"`
	Metadata  map[string]any `json:"metadata"`
	CreatedAt time.Time      `json:"createdAt"`
	UpdatedAt time.Time      `json:"updatedAt"`
}

// CreateMemoryRequest is the body for POST /v4/memories.
type CreateMemoryRequest struct {
	ContainerTag string   `json:"containerTag"`
	Memories     []Memory `json:"memories"`
}

// CreateMemoryResponse is the response from POST /v4/memories.
type CreateMemoryResponse struct {
	DocumentID string       `json:"documentId"`
	Memories   []MemoryInfo `json:"memories"`
}

// SearchRequest is the body for POST /v4/search.
type SearchRequest struct {
	Query        string         `json:"query"`
	ContainerTag string         `json:"containerTag,omitempty"`
	Limit        int            `json:"limit,omitempty"`
	Filters      map[string]any `json:"filters,omitempty"`
}

// SearchResult is a single result from POST /v4/search.
type SearchResult struct {
	ID         string         `json:"id"`
	Memory     string         `json:"memory"`
	Similarity float64        `json:"similarity"`
	Metadata   map[string]any `json:"metadata"`
	UpdatedAt  time.Time      `json:"updatedAt"`
}

// SearchResponse is the response from POST /v4/search.
type SearchResponse struct {
	Results []SearchResult `json:"results"`
	Total   int            `json:"total"`
	Timing  int            `json:"timing"`
}

// UpdateMemoryRequest is the body for PATCH /v4/memories.
type UpdateMemoryRequest struct {
	ContainerTag string `json:"containerTag"`
	ID           string `json:"id"`
	NewContent   string `json:"newContent"`
}

// UpdateMemoryResponse is the response from PATCH /v4/memories.
type UpdateMemoryResponse struct {
	ID             string    `json:"id"`
	Memory         string    `json:"memory"`
	Version        int       `json:"version"`
	ParentMemoryID string    `json:"parentMemoryId"`
	CreatedAt      time.Time `json:"createdAt"`
}

// DeleteMemoryResponse is the response from DELETE /v4/memories/{id}.
type DeleteMemoryResponse struct {
	ID        string `json:"id"`
	Forgotten bool   `json:"forgotten"`
}

// ─── Client ────────────────────────────────────────────────────────────────

// Client is the Supermemory v4 API client.
type Client struct {
	cfg  Config
	http *http.Client
}

// NewClient creates a new Supermemory client with the given configuration.
func NewClient(cfg Config) *Client {
	cfg.defaults()
	return &Client{
		cfg:  cfg,
		http: &http.Client{Timeout: cfg.Timeout},
	}
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var bodyReader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("supermemory marshal: %w", err)
		}
		bodyReader = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.cfg.BaseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("supermemory new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if c.cfg.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.cfg.APIKey)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("supermemory http: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == 204 {
		return nil
	}
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		var errBody struct {
			Detail  any    `json:"detail"`
			Message string `json:"message"`
		}
		_ = json.Unmarshal(data, &errBody)
		msg := fmt.Sprintf("%v", errBody.Detail)
		if errBody.Message != "" {
			msg = errBody.Message
		}
		return fmt.Errorf("supermemory api error %d: %s", resp.StatusCode, msg)
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("supermemory unmarshal: %w", err)
		}
	}
	return nil
}

// ─── API Methods ───────────────────────────────────────────────────────────

// CreateMemory stores one or more memories under containerTag.
// Maps to: POST /v4/memories
func (c *Client) CreateMemory(ctx context.Context, containerTag string, memories []Memory) (*CreateMemoryResponse, error) {
	body := CreateMemoryRequest{
		ContainerTag: containerTag,
		Memories:     memories,
	}
	var out CreateMemoryResponse
	if err := c.do(ctx, http.MethodPost, "/v4/memories", body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// SearchMemory queries memories by text. ContainerTag scopes the search to a project.
// Maps to: POST /v4/search
func (c *Client) SearchMemory(ctx context.Context, req SearchRequest) (*SearchResponse, error) {
	if req.Limit == 0 {
		req.Limit = 10
	}
	var out SearchResponse
	if err := c.do(ctx, http.MethodPost, "/v4/search", req, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// UpdateMemory creates a new version of an existing memory.
// Maps to: PATCH /v4/memories
func (c *Client) UpdateMemory(ctx context.Context, containerTag, memoryID, newContent string) (*UpdateMemoryResponse, error) {
	body := UpdateMemoryRequest{
		ContainerTag: containerTag,
		ID:           memoryID,
		NewContent:   newContent,
	}
	var out UpdateMemoryResponse
	if err := c.do(ctx, http.MethodPatch, "/v4/memories", body, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// DeleteMemory soft-deletes (forgets) a memory by ID.
// Maps to: DELETE /v4/memories/{id}
func (c *Client) DeleteMemory(ctx context.Context, memoryID string) (*DeleteMemoryResponse, error) {
	var out DeleteMemoryResponse
	if err := c.do(ctx, http.MethodDelete, fmt.Sprintf("/v4/memories/%s", memoryID), nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// Health checks the Supermemory server health.
func (c *Client) Health(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	if err := c.do(ctx, http.MethodGet, "/health", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}
