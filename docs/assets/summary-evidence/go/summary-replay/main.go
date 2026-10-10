//go:build tracelab_replay

// Event-time experiment adapter. Accounting remains in the existing connector.
package main

import (
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	connector "github.com/llm-measurement/otelcol-genai-sketches/connector/genaisketchconnector"
	"github.com/llm-measurement/otelcol-genai-sketches/connector/genaisketchconnector/internal/replay"
	"github.com/llm-measurement/otelcol-genai-sketches/connector/genaisketchconnector/internal/tracelab"
	"go.opentelemetry.io/collector/component"
	otelconnector "go.opentelemetry.io/collector/connector"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.opentelemetry.io/collector/pdata/ptrace"
	"go.uber.org/zap"
)

type event struct {
	at            time.Time
	trace         *tracelab.Row
	input, output int64
}
type group struct {
	Name, Provider, Model, Directory string
	Events                           []event `json:"-"`
	Rows                             int
}
type manifest struct {
	Dataset, Start, End        string
	Groups                     []*group
	ReadSeconds, ReplaySeconds float64
	Rows                       int
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	dataset := flag.String("dataset", "", "tracelab or burstgpt")
	data := flag.String("data", "", "pinned data directory")
	out := flag.String("out", "", "new output directory")
	flag.Parse()
	if *dataset != "tracelab" && *dataset != "burstgpt" {
		return errors.New("unknown dataset")
	}
	secret := os.Getenv("GENAI_SKETCH_SECRET")
	if len(secret) < 32 {
		return errors.New("test key required")
	}
	started := time.Now()
	groups := map[string]*group{}
	add := func(name, provider, model string, e event) {
		g := groups[name]
		if g == nil {
			g = &group{Name: name, Provider: provider, Model: model}
			groups[name] = g
		}
		g.Events = append(g.Events, e)
		g.Rows++
	}
	start, _ := time.Parse("2006-01-02", "2025-09-23")
	end, _ := time.Parse("2006-01-02", "2026-07-25")
	count := 0
	if *dataset == "tracelab" {
		path := filepath.Join(*data, "syfi_coding_trace.jsonl.gz")
		if err := verify(path, tracelab.SHA256); err != nil {
			return err
		}
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		gz, err := gzip.NewReader(f)
		if err != nil {
			return err
		}
		rows, err := tracelab.Read(gz)
		if err = errors.Join(err, gz.Close()); err != nil {
			return err
		}
		for i := range rows {
			r := &rows[i]
			if r.At.Before(start) || !r.At.Before(end) {
				return errors.New("trace outside registered interval")
			}
			add("cell:"+r.Provider+":"+r.Model, r.Provider, r.Model, event{at: r.At, trace: r})
			count++
		}
	} else {
		start, _ = time.Parse("2006-01-02", "2024-01-01")
		end = start
		hashes := []string{"4bb3783693d0a435686fbfc885615d2349bd067239079fa4b749f2e679e12122", "44bf5942b03fca42c01a226a545ad3a750ec62688faecd67b6831c56a8928bf7"}
		for idx, want := range hashes {
			path := filepath.Join(*data, fmt.Sprintf("BurstGPT_%d.csv", idx+1))
			if err := verify(path, want); err != nil {
				return err
			}
			f, err := os.Open(path)
			if err != nil {
				return err
			}
			r := csv.NewReader(f)
			header, err := r.Read()
			if err != nil {
				return err
			}
			expected := []string{"Timestamp", "Model", "Request tokens", "Response tokens", "Total tokens", "Log Type"}
			if fmt.Sprint(header) != fmt.Sprint(expected) {
				return errors.New("CSV schema mismatch")
			}
			for {
				row, err := r.Read()
				if err == io.EOF {
					break
				}
				if err != nil {
					return err
				}
				sec, e1 := strconv.ParseFloat(row[0], 64)
				in, e2 := strconv.ParseInt(row[2], 10, 64)
				output, e3 := strconv.ParseInt(row[3], 10, 64)
				total, e4 := strconv.ParseInt(row[4], 10, 64)
				if e1 != nil || e2 != nil || e3 != nil || e4 != nil || sec < 0 || in < 0 || output < 0 || total != in+output {
					return errors.New("invalid CSV value")
				}
				at := start.Add(time.Duration(sec * 1e9))
				if !at.Before(end) {
					end = at.Truncate(24 * time.Hour).Add(24 * time.Hour)
				}
				add("model:"+row[1], "azure", row[1], event{at: at, input: in, output: output})
				count++
			}
			if err := f.Close(); err != nil {
				return err
			}
		}
	}
	readSeconds := time.Since(started).Seconds()
	if err := os.Mkdir(*out, 0700); err != nil {
		return err
	}
	names := make([]string, 0, len(groups))
	for name := range groups {
		names = append(names, name)
	}
	sort.Strings(names)
	m := manifest{Dataset: *dataset, Start: start.Format("2006-01-02"), End: end.Format("2006-01-02"), ReadSeconds: readSeconds, Rows: count}
	replayStart := time.Now()
	for index, name := range names {
		g := groups[name]
		sort.SliceStable(g.Events, func(i, j int) bool { return g.Events[i].at.Before(g.Events[j].at) })
		g.Directory = fmt.Sprintf("g%03d", index)
		dir := filepath.Join(*out, g.Directory)
		if err := os.Mkdir(dir, 0700); err != nil {
			return err
		}
		scratch, err := os.MkdirTemp(filepath.Dir(*out), ".summary-evidence-")
		if err != nil {
			return err
		}
		cfg := connector.NewFactory().CreateDefaultConfig().(*connector.Config)
		cfg.WindowDuration = 24 * time.Hour
		cfg.RetentionWindows = 2
		cfg.MaxSlices = 1
		cfg.Slices = []connector.SliceConfig{{Name: "app", Keys: []string{"service.name"}, FromResourceAttributes: []string{"service.name"}}}
		cfg.TopK = 100
		cfg.TopKKeys = []connector.TopKKeyConfig{{Field: "prompt_key", Weight: "tokens"}, {Field: "user_key", Weight: "tokens"}, {Field: "session_key", Weight: "tokens"}}
		cfg.Fields["prompt_key"] = connector.FieldConfig{FromAttributes: []string{"summary_evidence.accounting.group"}, Canonicalization: "text_v1", Domain: "prompt:v1"}
		keyID := sha256.Sum256([]byte(secret))
		cfg.SummaryExport = connector.SummaryExportConfig{Directory: scratch, ProducerID: g.Directory, ScopeID: *dataset + "-summary-evidence", KeyID: hex.EncodeToString(keyID[:16]), Interval: time.Second}
		runner, err := newRunner(cfg)
		if err != nil {
			return err
		}
		i := 0
		epoch := sha256.Sum256([]byte(name + *dataset))
		err = runner.Replay(context.Background(), start, end, hex.EncodeToString(epoch[:16]), func() (time.Time, ptrace.Traces, error) {
			if i == len(g.Events) {
				return time.Time{}, ptrace.Traces{}, io.EOF
			}
			e := g.Events[i]
			i++
			var td ptrace.Traces
			if e.trace != nil {
				td = e.trace.Traces()
			} else {
				td = ptrace.NewTraces()
				rs := td.ResourceSpans().AppendEmpty()
				rs.Resource().Attributes().PutStr("service.name", "burstgpt")
				sp := rs.ScopeSpans().AppendEmpty().Spans().AppendEmpty()
				sp.SetName("chat")
				sp.SetKind(ptrace.SpanKindClient)
				sp.SetStartTimestamp(pcommon.NewTimestampFromTime(e.at))
				sp.SetEndTimestamp(pcommon.NewTimestampFromTime(e.at))
				a := sp.Attributes()
				a.PutStr("gen_ai.operation.name", "chat")
				a.PutStr("gen_ai.request.model", g.Model)
				a.PutInt("gen_ai.usage.input_tokens", e.input)
				if e.output > 0 {
					a.PutInt("gen_ai.usage.output_tokens", e.output)
				} else {
					sp.Status().SetCode(ptrace.StatusCodeError)
				}
			}
			td.ResourceSpans().At(0).ScopeSpans().At(0).Spans().At(0).Attributes().PutStr("summary_evidence.accounting.group", "all")
			return e.at, td, nil
		}, func(at time.Time, b []byte) error {
			return os.WriteFile(filepath.Join(dir, at.Format("2006-01-02")+".json"), b, 0600)
		})
		os.RemoveAll(scratch)
		if err != nil {
			return err
		}
		m.Groups = append(m.Groups, g)
		fmt.Printf("%s %d rows complete\n", g.Directory, g.Rows)
	}
	m.ReplaySeconds = time.Since(replayStart).Seconds()
	b, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(*out, "manifest.json"), b, 0600)
}
func verify(path, want string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return err
	}
	if hex.EncodeToString(h.Sum(nil)) != want {
		return errors.New("dataset hash mismatch")
	}
	return nil
}
func newRunner(cfg *connector.Config) (replay.Runner, error) {
	sink, err := consumer.NewMetrics(func(context.Context, pmetric.Metrics) error { return nil })
	if err != nil {
		return nil, err
	}
	factory := connector.NewFactory()
	instance, err := factory.CreateTracesToMetrics(context.Background(), otelconnector.Settings{ID: component.NewID(factory.Type()), TelemetrySettings: component.TelemetrySettings{Logger: zap.NewNop()}}, cfg, sink)
	if err != nil {
		return nil, err
	}
	r, ok := instance.(replay.Runner)
	if !ok {
		return nil, errors.New("replay unavailable")
	}
	return r, nil
}
