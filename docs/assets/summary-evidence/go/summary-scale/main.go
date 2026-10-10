package main

import (
	"encoding/json"
	"fmt"
	fi "github.com/llm-measurement/llm-sketchkit/go/sketchkit/frequentitems"
	sh "github.com/llm-measurement/llm-sketchkit/go/sketchkit/hash"
	"github.com/llm-measurement/llm-sketchkit/go/sketchkit/hllpp"
	"math"
	"math/rand"
	"os"
	"runtime"
	"sort"
	"strconv"
	"time"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	if len(os.Args) != 3 && len(os.Args) != 5 {
		return fmt.Errorf("weights JSON and output directory required")
	}
	b, err := os.ReadFile(os.Args[1])
	if err != nil {
		return err
	}
	var weights []int64
	if err = json.Unmarshal(b, &weights); err != nil {
		return err
	}
	if len(weights) == 0 {
		return fmt.Errorf("empty weights")
	}
	if err = os.Mkdir(os.Args[2], 0700); err != nil {
		return err
	}
	secret, err := sh.SecretFromEnv("GENAI_SKETCH_SECRET")
	if err != nil {
		return err
	}
	var results []map[string]any
	ns := []int{1000, 10000, 100000, 1000000}
	seeds := []int64{20261010, 20261011, 20261012}
	if len(os.Args) == 5 {
		n, e1 := strconv.Atoi(os.Args[3])
		seed, e2 := strconv.ParseInt(os.Args[4], 10, 64)
		if e1 != nil || e2 != nil {
			return fmt.Errorf("invalid run selector")
		}
		ns = []int{n}
		seeds = []int64{seed}
	}
	for _, n := range ns {
		for _, seed := range seeds {
			runtime.GC()
			var base, after runtime.MemStats
			runtime.ReadMemStats(&base)
			h, _ := hllpp.New(hllpp.ProfileSmall, sh.UserV1, sh.HMACSHA25664)
			f, _ := fi.New(fi.ProfileSmall, sh.UserV1, sh.HMACSHA25664)
			t := time.Now()
			walk(n, seed, weights, secret, func(k uint64, w int64) {
				h.AddHash(k)
				if err := f.AddHash(k, w); err != nil {
					panic(err)
				}
			})
			elapsed := time.Since(t).Seconds()
			runtime.GC()
			runtime.ReadMemStats(&after)
			allocated := int64(after.HeapAlloc) - int64(base.HeapAlloc)
			hb, _ := h.MarshalBinary()
			fb, _ := f.MarshalBinary()
			runtime.KeepAlive(h)
			runtime.KeepAlive(f)
			runtime.GC()
			var exactBefore, exactAfter runtime.MemStats
			runtime.ReadMemStats(&exactBefore)
			truth := map[uint64]int64{}
			walk(n, seed, weights, secret, func(k uint64, w int64) { truth[k] += w })
			runtime.GC()
			runtime.ReadMemStats(&exactAfter)
			exactAllocated := int64(exactAfter.HeapAlloc) - int64(exactBefore.HeapAlloc)
			candidates, _ := f.FrequentItems(fi.NoFalseNegatives)
			sort.Slice(candidates, func(i, j int) bool {
				if candidates[i].Estimate == candidates[j].Estimate {
					return candidates[i].Hash < candidates[j].Hash
				}
				return candidates[i].Estimate > candidates[j].Estimate
			})
			keys := make([]uint64, 0, len(truth))
			for k := range truth {
				keys = append(keys, k)
			}
			sort.Slice(keys, func(i, j int) bool {
				if truth[keys[i]] == truth[keys[j]] {
					return keys[i] < keys[j]
				}
				return truth[keys[i]] > truth[keys[j]]
			})
			trueTop := map[uint64]bool{}
			for _, k := range keys[:20] {
				trueTop[k] = true
			}
			matches := 0
			for i, item := range candidates {
				if i == 20 {
					break
				}
				if trueTop[item.Hash] {
					matches++
				}
			}
			violations, untracked := 0, 0
			var total int64
			for k, v := range truth {
				total += v
				if v < f.LowerBoundHash(k) || v > f.UpperBoundHash(k) {
					violations++
				}
				if f.LowerBoundHash(k) == 0 {
					untracked++
				}
			}
			exactJSON, _ := json.Marshal(truth)
			record := map[string]any{"n": n, "seed": seed, "events": 5 * n, "distinct_estimate": h.Estimate(), "distinct_relative_error": math.Abs(h.Estimate()-float64(n)) / float64(n), "hll_bytes": len(hb), "fi_bytes": len(fb), "hll_register_storage_bytes": h.RegisterStorageBytes(), "fi_capacity": f.MapSize(), "heap_delta_bytes": allocated, "exact_json_bytes": len(exactJSON), "exact_table_entries": len(truth), "minimum_exact_key_weight_payload_bytes": 16 * len(truth), "top20_precision": float64(matches) / 20, "top20_recall": float64(matches) / 20, "bound_violations": violations, "untracked_checked": untracked, "weight_conserved": f.TotalWeight() == total, "seconds": elapsed, "per_user_metric_series": 12 * n, "aggregate_metric_series": 12}
			results = append(results, record)
			record["exact_heap_delta_bytes"] = exactAllocated
			record["isolated_process"] = len(os.Args) == 5
			raw, _ := json.MarshalIndent(results, "", "  ")
			if err = os.WriteFile(os.Args[2]+"/results.json", raw, 0600); err != nil {
				return err
			}
			if err = os.WriteFile(fmt.Sprintf("%s/n%d-seed%d-hll.pb", os.Args[2], n, seed), hb, 0600); err != nil {
				return err
			}
			if err = os.WriteFile(fmt.Sprintf("%s/n%d-seed%d-fi.pb", os.Args[2], n, seed), fb, 0600); err != nil {
				return err
			}
			fmt.Printf("N=%d seed=%d error=%.4f bounds=%d\n", n, seed, record["distinct_relative_error"], violations)
		}
	}
	return nil
}
func walk(n int, seed int64, weights []int64, secret sh.Secret, emit func(uint64, int64)) {
	r := rand.New(rand.NewSource(seed))
	zipf := rand.NewZipf(r, 1.2, 1, uint64(n-1))
	for i := 0; i < 5*n; i++ {
		id := uint64(i)
		if i >= n {
			id = zipf.Uint64()
		}
		key, err := sh.Hash64(secret, sh.UserV1, []byte(strconv.FormatInt(seed, 10)+":"+strconv.FormatUint(id, 10)))
		if err != nil {
			panic(err)
		}
		emit(key, weights[r.Intn(len(weights))])
	}
}
