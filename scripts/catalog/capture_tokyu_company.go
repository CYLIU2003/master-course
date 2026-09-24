// Command capture_tokyu_company manually freezes Tokyu Bus ODPT timetable data.
// It uses only the Go standard library. Prepare and job submission never invoke it.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	operator     = "odpt.Operator:TokyuBus"
	baseURL      = "https://api.odpt.org/api/v4/"
	manifestName = "capture_manifest.json"
)

type requestInfo struct {
	Endpoint string            `json:"endpoint"`
	Query    map[string]string `json:"query"`
}

type source struct {
	Resource       string      `json:"resource"`
	Request        requestInfo `json:"request"`
	SHA256         string      `json:"sha256"`
	RetrievedAtUTC string      `json:"retrieved_at_utc"`
	RecordCount    int         `json:"record_count"`
	Path           string      `json:"path"`
	DataKind       string      `json:"data_kind"`
}

type captureManifest struct {
	SchemaVersion            string   `json:"schema_version"`
	OperatorID               string   `json:"operator_id"`
	CapturedAtUTC            string   `json:"captured_at_utc"`
	Status                   string   `json:"status"`
	Sources                  []source `json:"sources"`
	PatternCount             int      `json:"pattern_count"`
	RouteCount               int      `json:"route_count"`
	StopPartitionCount       int      `json:"stop_partition_count"`
	TimetableObjectCount     int      `json:"timetable_object_count"`
	StopTimetableObjectCount int      `json:"stop_timetable_object_count"`
	Claim                    string   `json:"claim"`
}

type row map[string]json.RawMessage

type requestGate struct {
	mu       sync.Mutex
	next     time.Time
	interval time.Duration
}

func (gate *requestGate) wait(ctx context.Context) error {
	gate.mu.Lock()
	now := time.Now()
	start := now
	if gate.next.After(start) {
		start = gate.next
	}
	gate.next = start.Add(gate.interval)
	gate.mu.Unlock()
	if delay := time.Until(start); delay > 0 {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}
	}
	return nil
}

func (gate *requestGate) pause(delay time.Duration) {
	gate.mu.Lock()
	defer gate.mu.Unlock()
	until := time.Now().Add(delay)
	if until.After(gate.next) {
		gate.next = until
	}
}

func stringField(record row, field string) string {
	var value string
	_ = json.Unmarshal(record[field], &value)
	return value
}

func stringList(record row, field string) []string {
	var values []string
	if json.Unmarshal(record[field], &values) == nil {
		return values
	}
	value := stringField(record, field)
	if value != "" {
		return []string{value}
	}
	return nil
}

func contains(values []string, expected string) bool {
	for _, value := range values {
		if value == expected {
			return true
		}
	}
	return false
}

func validateRows(resource string, records []row) error {
	seen := make(map[string]bool, len(records))
	for _, record := range records {
		id := stringField(record, "owl:sameAs")
		if id == "" || seen[id] || !contains(stringList(record, "odpt:operator"), operator) {
			return fmt.Errorf("%s contains a missing/duplicate ID or operator mismatch", resource)
		}
		seen[id] = true
	}
	return nil
}

func sha(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func fileStem(resource string, query map[string]string) string {
	keys := make([]string, 0, len(query))
	for key := range query {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	var parts []string
	for _, key := range keys {
		parts = append(parts, key+"="+query[key])
	}
	id := sha([]byte(resource + "?" + strings.Join(parts, "&")))[:20]
	return strings.ReplaceAll(resource, ":", "_") + "_" + id
}

func writeExclusive(path string, raw []byte) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	if _, err = file.Write(raw); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func readOrFetch(ctx context.Context, client *http.Client, gate *requestGate, output, key, resource string, query map[string]string) (source, []row, error) {
	info := requestInfo{Endpoint: baseURL + resource, Query: query}
	stem := fileStem(resource, query)
	rawPath := filepath.Join(output, stem+".json")
	metaPath := filepath.Join(output, stem+".manifest.json")
	var meta source
	var raw []byte
	var err error
	if _, statErr := os.Stat(rawPath); statErr == nil {
		if raw, err = os.ReadFile(rawPath); err != nil {
			return meta, nil, err
		}
		metadata, readErr := os.ReadFile(metaPath)
		if readErr != nil || json.Unmarshal(metadata, &meta) != nil || meta.SHA256 != sha(raw) ||
			meta.Resource != resource || meta.Path != rawPath || meta.Request.Endpoint != info.Endpoint || !sameQuery(meta.Request.Query, query) {
			return meta, nil, fmt.Errorf("existing raw/manifest provenance mismatch: %s", stem)
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return meta, nil, statErr
	} else {
		if _, err := os.Stat(metaPath); err == nil {
			return meta, nil, fmt.Errorf("orphan manifest: %s", stem)
		}
		values := url.Values{}
		for field, value := range query {
			values.Set(field, value)
		}
		values.Set("acl:consumerKey", key)
		for attempt := 0; attempt < 8; attempt++ {
			if err := gate.wait(ctx); err != nil {
				return meta, nil, fmt.Errorf("capture cancelled for %s", resource)
			}
			request, makeErr := http.NewRequestWithContext(ctx, http.MethodGet, info.Endpoint+"?"+values.Encode(), nil)
			if makeErr != nil {
				return meta, nil, fmt.Errorf("request construction failed for %s", resource)
			}
			request.Header.Set("Accept", "application/json")
			request.Header.Set("User-Agent", "master-course-frozen-odpt-go/1")
			response, doErr := client.Do(request)
			if doErr == nil {
				if response.StatusCode == 200 {
					raw, err = io.ReadAll(io.LimitReader(response.Body, 150<<20))
					response.Body.Close()
					if err == nil && len(raw) < 150<<20 {
						break
					}
					return meta, nil, fmt.Errorf("response read/size failure for %s", resource)
				}
				retryAfter := response.Header.Get("Retry-After")
				response.Body.Close()
				if response.StatusCode != 429 && response.StatusCode < 500 {
					return meta, nil, fmt.Errorf("ODPT %s returned HTTP %d", resource, response.StatusCode)
				}
				if attempt == 7 {
					return meta, nil, fmt.Errorf("ODPT %s returned HTTP %d after retries", resource, response.StatusCode)
				}
				if response.StatusCode == 429 {
					wait := time.Duration(10*(attempt+1)) * time.Second
					if seconds, parseErr := time.ParseDuration(retryAfter + "s"); parseErr == nil && seconds > wait {
						wait = seconds
					} else if date, parseErr := http.ParseTime(retryAfter); parseErr == nil && time.Until(date) > wait {
						wait = time.Until(date)
					}
					gate.pause(wait)
					fmt.Printf("ODPT rate limited; waiting at least %s before retry\n", wait.Round(time.Second))
				}
			} else if attempt == 7 {
				// url.Error includes the token-bearing URL, so never format it.
				return meta, nil, fmt.Errorf("network failure for %s after retries", resource)
			}
			select {
			case <-ctx.Done():
				return meta, nil, fmt.Errorf("capture cancelled for %s", resource)
			case <-time.After(time.Duration(attempt+1) * time.Second):
			}
		}
		meta = source{Resource: resource, Request: info, SHA256: sha(raw),
			RetrievedAtUTC: time.Now().UTC().Format(time.RFC3339), Path: rawPath,
			DataKind: "official_current_scheduled_service_not_historical_actual_operations"}
	}
	var records []row
	if err := json.Unmarshal(raw, &records); err != nil {
		return meta, nil, fmt.Errorf("invalid JSON array for %s", resource)
	}
	if err := validateRows(resource, records); err != nil {
		return meta, nil, err
	}
	if meta.RecordCount != 0 && meta.RecordCount != len(records) {
		return meta, nil, fmt.Errorf("stored count mismatch for %s", stem)
	}
	if meta.RecordCount == 0 && meta.SHA256 == sha(raw) {
		meta.RecordCount = len(records)
		if _, err := os.Stat(rawPath); errors.Is(err, os.ErrNotExist) {
			if err := writeExclusive(rawPath, raw); err != nil {
				return meta, nil, err
			}
			metadata, _ := json.MarshalIndent(meta, "", "  ")
			if err := writeExclusive(metaPath, append(metadata, '\n')); err != nil {
				return meta, nil, err
			}
		}
	}
	return meta, records, nil
}

func sameQuery(left, right map[string]string) bool {
	if len(left) != len(right) {
		return false
	}
	for key, value := range left {
		if right[key] != value {
			return false
		}
	}
	return true
}

type task struct{ resource, field, identifier string }
type result struct {
	task   task
	source source
	ids    []string
	err    error
}

func runPartitioned(ctx context.Context, client *http.Client, gate *requestGate, output, key string, tasks []task, workers int) ([]source, map[string]bool, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	work := make(chan task)
	results := make(chan result, workers)
	var group sync.WaitGroup
	for index := 0; index < workers; index++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for item := range work {
				query := map[string]string{"odpt:operator": operator, item.field: item.identifier}
				meta, records, err := readOrFetch(ctx, client, gate, output, key, item.resource, query)
				ids := make([]string, 0, len(records))
				if err == nil && len(records) >= 1000 {
					err = fmt.Errorf("%s partition reached 1000 records; finer filter required: %s", item.resource, item.identifier)
				}
				if err == nil {
					for _, record := range records {
						if !contains(stringList(record, item.field), item.identifier) {
							err = fmt.Errorf("ODPT filter not honored for %s: %s", item.resource, item.identifier)
							break
						}
						ids = append(ids, stringField(record, "owl:sameAs"))
					}
				}
				results <- result{task: item, source: meta, ids: ids, err: err}
			}
		}()
	}
	go func() {
		defer close(work)
		for _, item := range tasks {
			select {
			case <-ctx.Done():
				return
			case work <- item:
			}
		}
	}()
	go func() { group.Wait(); close(results) }()
	allSources := make([]source, 0, len(tasks))
	ids := make(map[string]bool)
	var firstErr error
	count := 0
	for item := range results {
		count++
		if item.err != nil && firstErr == nil {
			firstErr = item.err
			cancel()
		}
		if item.err == nil {
			allSources = append(allSources, item.source)
			for _, id := range item.ids {
				ids[id] = true
			}
		}
		if count%50 == 0 {
			fmt.Printf("%s partitions: %d/%d\n", tasks[0].resource, count, len(tasks))
		}
	}
	if firstErr != nil {
		return nil, nil, firstErr
	}
	if count != len(tasks) {
		return nil, nil, fmt.Errorf("capture ended after %d/%d partitions", count, len(tasks))
	}
	sort.Slice(allSources, func(i, j int) bool { return allSources[i].Path < allSources[j].Path })
	return allSources, ids, nil
}

func main() {
	outputFlag := flag.String("output", "", "new immutable output directory; rerun same directory to resume partial capture")
	workers := flag.Int("workers", 4, "maximum concurrent ODPT requests")
	intervalMS := flag.Int("interval-ms", 1000, "minimum interval between ODPT requests across workers")
	probe := flag.Bool("probe-pagination", false, "diagnose safe partition fields without freezing a capture")
	flag.Parse()
	if *outputFlag == "" || *workers < 1 || *workers > 8 || *intervalMS < 250 {
		fmt.Fprintln(os.Stderr, "--output and --workers=1..8 are required")
		os.Exit(2)
	}
	key := os.Getenv("ODPT_CONSUMER_KEY")
	if key == "" {
		fmt.Fprintln(os.Stderr, "ODPT_CONSUMER_KEY is required in the child environment")
		os.Exit(2)
	}
	output, err := filepath.Abs(*outputFlag)
	if err != nil {
		fmt.Fprintln(os.Stderr, "invalid output path")
		os.Exit(2)
	}
	if _, err := os.Stat(filepath.Join(output, manifestName)); err == nil {
		fmt.Fprintln(os.Stderr, "capture is already frozen; choose a new directory")
		os.Exit(2)
	}
	if err := os.MkdirAll(output, 0700); err != nil {
		fmt.Fprintln(os.Stderr, "cannot create output directory")
		os.Exit(1)
	}
	client := &http.Client{Timeout: 120 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirect refused") }}
	gate := &requestGate{interval: time.Duration(*intervalMS) * time.Millisecond}
	ctx := context.Background()
	if *probe {
		baseQuery := map[string]string{"odpt:operator": operator}
		_, firstPage, err := readOrFetch(ctx, client, gate, output, key, "odpt:BusstopPoleTimetable", baseQuery)
		if err != nil || len(firstPage) == 0 {
			fmt.Fprintln(os.Stderr, "cannot read first stop timetable page")
			os.Exit(1)
		}
		firstID := stringField(firstPage[0], "owl:sameAs")
		_, stopsForProbe, err := readOrFetch(ctx, client, gate, output, key, "odpt:BusstopPole", baseQuery)
		if err != nil || len(stopsForProbe) == 0 {
			fmt.Fprintln(os.Stderr, "cannot read stop master for probe")
			os.Exit(1)
		}
		stopID := stringField(stopsForProbe[0], "owl:sameAs")
		candidates := []map[string]string{
			{"odpt:operator": operator, "$skip": "1000"},
			{"odpt:operator": operator, "@offset": "1000"},
			{"odpt:operator": operator, "skip": "1000"},
			{"odpt:operator": operator, "offset": "1000"},
			{"odpt:operator": operator, "odpt:busstopPole": stopID},
		}
		for _, query := range candidates {
			_, records, err := readOrFetch(ctx, client, gate, output, key, "odpt:BusstopPoleTimetable", query)
			field := ""
			for candidate := range query {
				if candidate != "odpt:operator" {
					field = candidate
				}
			}
			if err != nil {
				fmt.Printf("probe %s: failed\n", field)
				continue
			}
			first := ""
			if len(records) > 0 {
				first = stringField(records[0], "owl:sameAs")
			}
			fmt.Printf("probe %s: records=%d first_same_as_unfiltered=%t\n", field, len(records), first == firstID)
		}
		return
	}
	var sources []source
	patternsSource, patterns, err := readOrFetch(ctx, client, gate, output, key, "odpt:BusroutePattern", map[string]string{"odpt:operator": operator})
	if err != nil || len(patterns) == 0 || len(patterns) >= 1000 {
		fmt.Fprintln(os.Stderr, "route pattern master missing, invalid, or capped")
		os.Exit(1)
	}
	sources = append(sources, patternsSource)
	stopsSource, stops, err := readOrFetch(ctx, client, gate, output, key, "odpt:BusstopPole", map[string]string{"odpt:operator": operator})
	if err != nil || len(stops) == 0 {
		fmt.Fprintln(os.Stderr, "bus stop master missing or invalid")
		os.Exit(1)
	}
	sources = append(sources, stopsSource)
	patternIDs, routeSet := make([]string, 0, len(patterns)), make(map[string]bool)
	for _, pattern := range patterns {
		patternIDs = append(patternIDs, stringField(pattern, "owl:sameAs"))
		for _, route := range stringList(pattern, "odpt:busroute") {
			routeSet[route] = true
		}
	}
	sort.Strings(patternIDs)
	routeIDs := make([]string, 0, len(routeSet))
	for route := range routeSet {
		routeIDs = append(routeIDs, route)
	}
	sort.Strings(routeIDs)
	if len(routeIDs) == 0 {
		fmt.Fprintln(os.Stderr, "no bus route IDs in pattern master")
		os.Exit(1)
	}
	fmt.Printf("master: %d patterns, %d stops, %d bus routes\n", len(patternIDs), len(stops), len(routeIDs))
	tasks := make([]task, 0, len(patternIDs))
	for _, id := range patternIDs {
		tasks = append(tasks, task{"odpt:BusTimetable", "odpt:busroutePattern", id})
	}
	timetableSources, timetableIDs, err := runPartitioned(ctx, client, gate, output, key, tasks, *workers)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	sources = append(sources, timetableSources...)
	stopIDs := make([]string, 0, len(stops))
	expectedStopTimetableIDs := make(map[string]bool)
	for _, stop := range stops {
		stopIDs = append(stopIDs, stringField(stop, "owl:sameAs"))
		for _, id := range stringList(stop, "odpt:busstopPoleTimetable") {
			expectedStopTimetableIDs[id] = true
		}
	}
	sort.Strings(stopIDs)
	tasks = tasks[:0]
	for _, id := range stopIDs {
		tasks = append(tasks, task{"odpt:BusstopPoleTimetable", "odpt:busstopPole", id})
	}
	stopSources, stopTimetableIDs, err := runPartitioned(ctx, client, gate, output, key, tasks, *workers)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	sources = append(sources, stopSources...)
	if len(stopTimetableIDs) != len(expectedStopTimetableIDs) {
		fmt.Fprintf(os.Stderr, "stop timetable reference count mismatch: captured=%d referenced=%d\n", len(stopTimetableIDs), len(expectedStopTimetableIDs))
		os.Exit(1)
	}
	for id := range expectedStopTimetableIDs {
		if !stopTimetableIDs[id] {
			fmt.Fprintln(os.Stderr, "stop timetable reference absent from partitioned capture")
			os.Exit(1)
		}
	}
	for _, resource := range []string{"odpt:BusTimetable", "odpt:BusstopPoleTimetable"} {
		meta, sample, err := readOrFetch(ctx, client, gate, output, key, resource, map[string]string{"odpt:operator": operator})
		if err != nil {
			fmt.Fprintln(os.Stderr, "broad sample validation failed for "+resource)
			os.Exit(1)
		}
		sources = append(sources, meta)
		ids := timetableIDs
		if resource == "odpt:BusstopPoleTimetable" {
			ids = stopTimetableIDs
		}
		for _, record := range sample {
			if !ids[stringField(record, "owl:sameAs")] {
				fmt.Fprintln(os.Stderr, "partitioned capture misses broad sample for "+resource)
				os.Exit(1)
			}
		}
	}
	if len(timetableIDs) == 0 || len(stopTimetableIDs) == 0 {
		fmt.Fprintln(os.Stderr, "timetable capture is empty")
		os.Exit(1)
	}
	manifest := captureManifest{SchemaVersion: "tokyu_company_odpt_capture_v1", OperatorID: operator,
		CapturedAtUTC: time.Now().UTC().Format(time.RFC3339), Status: "CAPTURED_NOT_BUILT", Sources: sources,
		PatternCount: len(patternIDs), RouteCount: len(routeIDs), StopPartitionCount: len(stopIDs), TimetableObjectCount: len(timetableIDs),
		StopTimetableObjectCount: len(stopTimetableIDs), Claim: "Current published schedule snapshot; not historical actual operations"}
	encoded, _ := json.MarshalIndent(manifest, "", "  ")
	if err := writeExclusive(filepath.Join(output, manifestName), append(encoded, '\n')); err != nil {
		fmt.Fprintln(os.Stderr, "cannot freeze capture manifest")
		os.Exit(1)
	}
	fmt.Printf("frozen: %d timetable objects, %d stop timetable objects\n", len(timetableIDs), len(stopTimetableIDs))
}
