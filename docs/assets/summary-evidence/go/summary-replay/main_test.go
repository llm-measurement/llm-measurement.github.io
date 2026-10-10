//go:build tracelab_replay

package main

import (
	"bytes"
	"context"
	"github.com/llm-measurement/llm-sketchkit/go/sketchkit/frequentitems"
	"github.com/llm-measurement/llm-sketchkit/go/sketchkit/summary"
	connector "github.com/llm-measurement/otelcol-genai-sketches/connector/genaisketchconnector"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestSentinelSummaryOnly(t *testing.T) {
	t.Setenv("GENAI_SKETCH_SECRET", "llm-measurement-summary-evidence-test-key-20261010")
	sentinels := []string{"SENTINEL-user-7391@example.invalid", "SENTINEL-session-88de42", "SENTINEL-prompt-41cd", "def SENTINEL_secret_function(): return 481921", "/private/SENTINEL-project/customer/secret.go"}
	start := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	cfg := connector.NewFactory().CreateDefaultConfig().(*connector.Config)
	cfg.WindowDuration = 24 * time.Hour
	cfg.RetentionWindows = 2
	cfg.MaxSlices = 1
	cfg.Slices = []connector.SliceConfig{{Name: "app", Keys: []string{"service.name"}, FromResourceAttributes: []string{"service.name"}}}
	cfg.TopKKeys = []connector.TopKKeyConfig{{Field: "prompt_key", Weight: "tokens"}, {Field: "user_key", Weight: "tokens"}, {Field: "session_key", Weight: "tokens"}}
	cfg.SummaryExport = connector.SummaryExportConfig{Directory: t.TempDir(), ProducerID: "sentinel", ScopeID: "summary-evidence-sentinel", KeyID: "public-test", Interval: time.Second}
	if err := os.Chmod(cfg.SummaryExport.Directory, 0700); err != nil {
		t.Fatal(err)
	}
	r, err := newRunner(cfg)
	if err != nil {
		t.Fatal(err)
	}
	used := false
	saved := 0
	err = r.Replay(context.Background(), start, start.Add(24*time.Hour), "0123456789abcdef0123456789abcdef", func() (time.Time, ptrace.Traces, error) {
		if used {
			return time.Time{}, ptrace.Traces{}, io.EOF
		}
		used = true
		at := start.Add(time.Hour)
		td := ptrace.NewTraces()
		rs := td.ResourceSpans().AppendEmpty()
		rs.Resource().Attributes().PutStr("service.name", "synthetic")
		sp := rs.ScopeSpans().AppendEmpty().Spans().AppendEmpty()
		sp.SetName(sentinels[2])
		sp.SetKind(ptrace.SpanKindClient)
		sp.SetStartTimestamp(pcommon.NewTimestampFromTime(at))
		sp.SetEndTimestamp(pcommon.NewTimestampFromTime(at))
		a := sp.Attributes()
		a.PutStr("gen_ai.operation.name", "chat")
		a.PutStr("gen_ai.request.model", "synthetic-model")
		a.PutStr("enduser.id", sentinels[0])
		a.PutStr("gen_ai.conversation.id", sentinels[1])
		a.PutStr("gen_ai.request.prompt", sentinels[2])
		a.PutStr("code.content", sentinels[3])
		a.PutStr("file.path", sentinels[4])
		a.PutInt("gen_ai.usage.input_tokens", 100)
		a.PutInt("gen_ai.usage.output_tokens", 10)
		failed := rs.ScopeSpans().At(0).Spans().AppendEmpty()
		sp.CopyTo(failed)
		failed.Attributes().PutInt("gen_ai.usage.input_tokens", 500)
		failed.Attributes().Remove("gen_ai.usage.output_tokens")
		failed.Status().SetCode(ptrace.StatusCodeError)
		return at, td, nil
	}, func(at time.Time, b []byte) error {
		saved++
		doc, err := summary.Parse(b)
		if err != nil {
			t.Fatal(err)
		}
		if doc.Counters["requests"] != 2 || doc.Counters["missing_token_usage"] != 1 || doc.Counters["input_tokens"] != 600 || doc.Counters["output_tokens"] != 10 {
			t.Fatal("failed attempt accounting mismatch")
		}
		weighted, err := frequentitems.Parse(doc.Sketches["top_prompts"].Data)
		if err != nil {
			t.Fatal(err)
		}
		if weighted.TotalWeight() != 110 {
			t.Fatal("partial input entered complete token weight")
		}
		for _, s := range sentinels {
			if bytes.Contains(b, []byte(s)) {
				t.Fatal("sentinel leaked")
			}
		}
		if out := os.Getenv("SUMMARY_EVIDENCE_SENTINEL_DIR"); out != "" {
			if err := os.MkdirAll(out, 0700); err != nil {
				return err
			}
			return os.WriteFile(filepath.Join(out, at.Format("2006-01-02")+".json"), b, 0600)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if saved != 1 {
		t.Fatalf("saved=%d", saved)
	}
}
