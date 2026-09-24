// Copyright 2026 coRoof contributors
// SPDX-License-Identifier: AGPL-3.0-only

package provider

import (
	"os"
	"strings"
	"testing"
)

func TestManifestBoundary(t *testing.T) {
	data, err := os.ReadFile("../../examples/provider.json")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Decode(strings.NewReader(string(data))); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*Manifest){
		"incompatible version": func(m *Manifest) { m.Spec.Protocol.Versions = []string{"9.0"} },
		"missing authority":    func(m *Manifest) { m.Spec.Authority.Domains = nil },
		"unknown type":         func(m *Manifest) { m.Spec.Type = "CUSTOM" },
		"blank identity":       func(m *Manifest) { m.Metadata.ID = " " },
		"plain HTTP":           func(m *Manifest) { m.Spec.Health.Href = "http://example.com/health" },
		"network relative URL": func(m *Manifest) { m.Spec.Health.Href = "//example.com/health" },
		"embedded credentials": func(m *Manifest) { m.Spec.Health.Href = "https://user:secret@example.com/health" },
		"duplicate domains":    func(m *Manifest) { m.Spec.Authority.Domains = []string{"sales.Contract", "sales.Contract"} },
	} {
		t.Run(name, func(t *testing.T) {
			m, _ := Decode(strings.NewReader(string(data)))
			mutate(&m)
			if m.Validate() == nil {
				t.Fatal("accepted invalid manifest")
			}
		})
	}
	for _, invalid := range []string{string(data) + " {}", strings.Replace(string(data), `"kind": "Provider"`, `"unexpected": true, "kind": "Provider"`, 1)} {
		if _, err := Decode(strings.NewReader(invalid)); err == nil {
			t.Fatal("accepted malformed envelope")
		}
	}
}
