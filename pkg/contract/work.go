// Copyright 2026 coRoof contributors
// SPDX-License-Identifier: AGPL-3.0-only

// Package contract defines the language-neutral work boundary.
package contract

type Metadata struct {
	ID       string `json:"id"`
	Tenant   string `json:"tenant"`
	Revision int    `json:"revision"`
}

type Ref struct {
	Ref string `json:"ref"`
}
type Work struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Type  string `json:"type"`
}
type Fact struct {
	ID         string `json:"id"`
	Label      string `json:"label"`
	Value      any    `json:"value"`
	Importance string `json:"importance"`
}
type Attention struct {
	ID       string `json:"id"`
	Severity string `json:"severity"`
	Reason   string `json:"reason"`
}
type Evidence struct {
	Ref   string `json:"ref"`
	Label string `json:"label"`
}
type Action struct {
	Capability           string `json:"capability"`
	Label                string `json:"label"`
	Availability         string `json:"availability"`
	Risk                 string `json:"risk"`
	RequiresConfirmation bool   `json:"requiresConfirmation"`
	Reason               string `json:"reason,omitempty"`
}
type WorkSpec struct {
	Actor     Ref         `json:"actor"`
	Work      Work        `json:"work"`
	Focus     Ref         `json:"focus"`
	Facts     []Fact      `json:"facts"`
	Attention []Attention `json:"attention"`
	Evidence  []Evidence  `json:"evidence"`
	Actions   []Action    `json:"actions"`
}
type WorkExperienceContract struct {
	APIVersion string   `json:"apiVersion"`
	Kind       string   `json:"kind"`
	Metadata   Metadata `json:"metadata"`
	Spec       WorkSpec `json:"spec"`
}
