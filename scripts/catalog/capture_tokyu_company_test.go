package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

func TestCachedCaptureChecksHashAndNeverPersistsKey(t *testing.T) {
	output := t.TempDir()
	resource := "odpt:BusTimetable"
	query := map[string]string{"odpt:operator": operator, "odpt:busroutePattern": "pattern-1"}
	stem := fileStem(resource, query)
	raw := []byte(`[{"owl:sameAs":"trip-1","odpt:operator":"odpt.Operator:TokyuBus","odpt:busroutePattern":"pattern-1"}]`)
	path := filepath.Join(output, stem+".json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	meta := source{Resource: resource, Request: requestInfo{Endpoint: baseURL + resource, Query: query},
		SHA256: sha(raw), RecordCount: 1, Path: path}
	encoded, err := json.Marshal(meta)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(output, stem+".manifest.json"), encoded, 0600); err != nil {
		t.Fatal(err)
	}
	gate := &requestGate{interval: time.Millisecond}
	loaded, records, err := readOrFetch(context.Background(), nil, gate, output, "private-test-key", resource, query)
	if err != nil || len(records) != 1 {
		t.Fatalf("cached read: %v, %d records", err, len(records))
	}
	if loaded.SHA256 != sha(raw) {
		t.Fatal("hash changed")
	}
	if strings.Contains(string(encoded), "private-test-key") {
		t.Fatal("key persisted")
	}
	if err := os.WriteFile(path, []byte(`[]`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := readOrFetch(context.Background(), nil, gate, output, "private-test-key", resource, query); err == nil {
		t.Fatal("tampered cached raw was accepted")
	}
}

func TestStopOperatorArrayAndDuplicateIDs(t *testing.T) {
	record := row{
		"owl:sameAs":    json.RawMessage(`"stop-1"`),
		"odpt:operator": json.RawMessage(`["odpt.Operator:TokyuBus"]`),
	}
	if err := validateRows("odpt:BusstopPole", []row{record}); err != nil {
		t.Fatal(err)
	}
	if err := validateRows("odpt:BusstopPole", []row{record, record}); err == nil {
		t.Fatal("duplicate ID was accepted")
	}
}

func TestRejectedSecondaryKeyFallsBackOnceWithoutRepeatingItsRequests(t *testing.T) {
	primaryRequests, secondaryRequests := 0, 0
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		key := request.URL.Query().Get("acl:consumerKey")
		if key == "secondary-test-key" {
			secondaryRequests++
			return &http.Response{StatusCode: 403, Body: io.NopCloser(strings.NewReader("forbidden")), Header: make(http.Header)}, nil
		}
		if key != "primary-test-key" {
			t.Fatal("unexpected credential")
		}
		primaryRequests++
		stopID := request.URL.Query().Get("odpt:busstopPole")
		body := fmt.Sprintf(`[{"owl:sameAs":"table-%s","odpt:operator":"%s","odpt:busstopPole":"%s"}]`, stopID, operator, stopID)
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}, nil
	})}
	tasks := make([]task, 4)
	for index := range tasks {
		tasks[index] = task{"odpt:BusstopPoleTimetable", "odpt:busstopPole", fmt.Sprintf("stop-%d", index)}
	}
	gates := []*requestGate{{interval: time.Millisecond}, {interval: time.Millisecond}}
	sources, ids, err := runPartitioned(context.Background(), client, gates, t.TempDir(), []string{"primary-test-key", "secondary-test-key"}, tasks, 1)
	if err != nil || len(sources) != 4 || len(ids) != 4 {
		t.Fatalf("fallback capture: %v, sources=%d, IDs=%d", err, len(sources), len(ids))
	}
	if primaryRequests != 4 || secondaryRequests != 1 {
		t.Fatalf("request counts primary=%d secondary=%d", primaryRequests, secondaryRequests)
	}
}
