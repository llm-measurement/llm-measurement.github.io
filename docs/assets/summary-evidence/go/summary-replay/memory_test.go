//go:build tracelab_replay

package main

import (
	"context"
	"encoding/json"
	"fmt"
	connector "github.com/llm-measurement/otelcol-genai-sketches/connector/genaisketchconnector"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"io"
	"os"
	"runtime"
	"testing"
	"time"
)

func TestSingleWindowMemory(t *testing.T) {
	out := os.Getenv("SUMMARY_EVIDENCE_MEMORY_OUT")
	if out == "" {
		t.Skip("explicit local output required")
	}
	t.Setenv("GENAI_SKETCH_SECRET", "llm-measurement-summary-evidence-test-key-20261010")
	var results []map[string]any
	for _, n := range []int{1000, 100000} {
		cfg := connector.NewFactory().CreateDefaultConfig().(*connector.Config)
		cfg.WindowDuration = 24 * time.Hour
		cfg.RetentionWindows = 2
		cfg.MaxSlices = 1
		cfg.Slices = []connector.SliceConfig{{Name: "app", Keys: []string{"service.name"}, FromResourceAttributes: []string{"service.name"}}}
		cfg.TopKKeys = []connector.TopKKeyConfig{{Field: "prompt_key", Weight: "tokens"}, {Field: "user_key", Weight: "tokens"}, {Field: "session_key", Weight: "tokens"}}
		cfg.SummaryExport = connector.SummaryExportConfig{Directory: t.TempDir(), ProducerID: "memory", ScopeID: "summary-evidence-memory", KeyID: "public-test", Interval: time.Second}
		if err := os.Chmod(cfg.SummaryExport.Directory, 0700); err != nil {
			t.Fatal(err)
		}
		runner, err := newRunner(cfg)
		if err != nil {
			t.Fatal(err)
		}
		start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
		i := 0
		var base, after runtime.MemStats
		err = runner.Replay(context.Background(), start, start.Add(24*time.Hour), "0123456789abcdef0123456789abcdef", func() (time.Time, ptrace.Traces, error) {
			if i == 0 {
				runtime.GC()
				runtime.ReadMemStats(&base)
			}
			if i == n {
				return time.Time{}, ptrace.Traces{}, io.EOF
			}
			i++
			at := start.Add(time.Hour + time.Duration(i)*time.Millisecond)
			td := ptrace.NewTraces()
			rs := td.ResourceSpans().AppendEmpty()
			rs.Resource().Attributes().PutStr("service.name", "synthetic")
			sp := rs.ScopeSpans().AppendEmpty().Spans().AppendEmpty()
			sp.SetName("chat")
			sp.SetKind(ptrace.SpanKindClient)
			sp.SetStartTimestamp(pcommon.NewTimestampFromTime(at))
			sp.SetEndTimestamp(pcommon.NewTimestampFromTime(at))
			a := sp.Attributes()
			a.PutStr("gen_ai.operation.name", "chat")
			a.PutStr("gen_ai.request.model", "synthetic")
			a.PutStr("enduser.id", fmt.Sprintf("user-%d", i))
			a.PutStr("gen_ai.conversation.id", fmt.Sprintf("session-%d", i))
			a.PutStr("gen_ai.request.prompt", fmt.Sprintf("prompt-%d", i))
			a.PutInt("gen_ai.usage.input_tokens", 100)
			a.PutInt("gen_ai.usage.output_tokens", 10)
			return at, td, nil
		}, func(_ time.Time, b []byte) error {
			runtime.GC()
			runtime.ReadMemStats(&after)
			runtime.KeepAlive(b)
			runtime.KeepAlive(runner)
			results = append(results, map[string]any{"cardinality_per_field": n, "active_slices": 1, "configured_retention_windows": 2, "populated_windows": 1, "ranking_fields": 3, "heap_delta_at_export_bytes": int64(after.HeapAlloc) - int64(base.HeapAlloc), "summary_bytes": len(b), "measurement": "Process retained-heap delta at export after GC; includes connector state, exporter snapshot and runtime bookkeeping, not only the sketch payload."})
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	b, _ := json.MarshalIndent(results, "", "  ")
	if err := os.WriteFile(out, b, 0600); err != nil {
		t.Fatal(err)
	}
}
