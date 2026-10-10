package main

import (
	"encoding/json"
	fi "github.com/llm-measurement/llm-sketchkit/go/sketchkit/frequentitems"
	sh "github.com/llm-measurement/llm-sketchkit/go/sketchkit/hash"
	"os"
	"sort"
	"testing"
)

func TestGrowthBounds(t *testing.T) {
	path := os.Getenv("SUMMARY_EVIDENCE_WEIGHTS")
	if path == "" {
		t.Skip("explicit local weight reservoir required")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var weights []int64
	if err = json.Unmarshal(raw, &weights); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GENAI_SKETCH_SECRET", "llm-measurement-summary-evidence-test-key-20261010")
	secret, err := sh.SecretFromEnv("GENAI_SKETCH_SECRET")
	if err != nil {
		t.Fatal(err)
	}
	var records []map[string]any
	for _, n := range []int{1000, 10000, 100000, 1000000} {
		for _, seed := range []int64{20261010, 20261011, 20261012} {
			a, _ := fi.New(fi.ProfileSmall, sh.UserV1, sh.HMACSHA25664)
			b, _ := fi.New(fi.ProfileSmall, sh.UserV1, sh.HMACSHA25664)
			exactA := map[uint64]int64{}
			exactB := map[uint64]int64{}
			walk(n, seed, weights, secret, func(k uint64, w int64) {
				after := w
				if k&31 == 0 {
					after *= 5
				}
				if err := a.AddHash(k, w); err != nil {
					t.Fatal(err)
				}
				if err := b.AddHash(k, after); err != nil {
					t.Fatal(err)
				}
				exactA[k] += w
				exactB[k] += after
			})
			violations := 0
			var exactDeltas, lowerDeltas []int64
			for k, av := range exactA {
				bv := exactB[k]
				delta := bv - av
				lo := b.LowerBoundHash(k) - a.UpperBoundHash(k)
				hi := b.UpperBoundHash(k) - a.LowerBoundHash(k)
				if delta < lo || delta > hi || av < a.LowerBoundHash(k) || av > a.UpperBoundHash(k) || bv < b.LowerBoundHash(k) || bv > b.UpperBoundHash(k) {
					violations++
				}
				exactDeltas = append(exactDeltas, delta)
			}
			ai, _ := a.FrequentItems(fi.NoFalseNegatives)
			bi, _ := b.FrequentItems(fi.NoFalseNegatives)
			candidates := map[uint64]bool{}
			for _, item := range append(ai, bi...) {
				candidates[item.Hash] = true
			}
			for k := range candidates {
				lowerDeltas = append(lowerDeltas, b.LowerBoundHash(k)-a.UpperBoundHash(k))
			}
			sort.Slice(exactDeltas, func(i, j int) bool { return exactDeltas[i] > exactDeltas[j] })
			sort.Slice(lowerDeltas, func(i, j int) bool { return lowerDeltas[i] > lowerDeltas[j] })
			growth := b.TotalWeight() - a.TotalWeight()
			exactFlag := exactDeltas[0]+exactDeltas[1] > growth/2
			sketchFlag := len(lowerDeltas) >= 2 && max(0, lowerDeltas[0])+max(0, lowerDeltas[1]) > growth/2
			records = append(records, map[string]any{"n": n, "seed": seed, "keys_checked": len(exactA), "bound_violations": violations, "growth": growth, "exact_fragile": exactFlag, "sketch_fragile": sketchFlag})
			if violations != 0 {
				t.Errorf("N=%d seed=%d violations=%d", n, seed, violations)
			}
		}
	}
	b, _ := json.MarshalIndent(records, "", "  ")
	if out := os.Getenv("SUMMARY_EVIDENCE_GROWTH_OUT"); out != "" {
		if err := os.WriteFile(out, b, 0600); err != nil {
			t.Fatal(err)
		}
	}
}
