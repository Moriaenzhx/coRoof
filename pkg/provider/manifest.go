// Copyright 2026 coRoof contributors
// SPDX-License-Identifier: AGPL-3.0-only

// Package provider contains generic Provider Protocol primitives.
package provider

import (
	"encoding/json"
	"fmt"
	"io"
	"net/url"
	"strings"
)

type Endpoint struct {
	Href string `json:"href"`
}
type Manifest struct {
	APIVersion string `json:"apiVersion"`
	Kind       string `json:"kind"`
	Metadata   struct {
		ID          string `json:"id"`
		DisplayName string `json:"displayName"`
		Version     string `json:"version"`
	} `json:"metadata"`
	Spec struct {
		Protocol struct {
			Versions []string `json:"versions"`
		} `json:"protocol"`
		Type      string `json:"type"`
		Authority struct {
			Domains []string `json:"domains"`
		} `json:"authority"`
		Discovery struct {
			Resources    Endpoint `json:"resources"`
			Capabilities Endpoint `json:"capabilities"`
			Schemas      Endpoint `json:"schemas"`
		} `json:"discovery"`
		Health         Endpoint `json:"health"`
		Authentication struct {
			Schemes []string `json:"schemes"`
		} `json:"authentication"`
	} `json:"spec"`
}

// Decode validates the supported bootstrap subset without making network calls.
func Decode(r io.Reader) (Manifest, error) {
	var m Manifest
	d := json.NewDecoder(r)
	d.DisallowUnknownFields()
	if err := d.Decode(&m); err != nil {
		return m, fmt.Errorf("decode manifest: %w", err)
	}
	if err := d.Decode(new(any)); err != io.EOF {
		return m, fmt.Errorf("manifest must contain exactly one JSON document")
	}
	return m, m.Validate()
}

func (m Manifest) Validate() error {
	if m.APIVersion != "coroof.io/provider/v0.1" || m.Kind != "Provider" {
		return fmt.Errorf("unsupported provider envelope")
	}
	for _, value := range []string{m.Metadata.ID, m.Metadata.DisplayName, m.Metadata.Version} {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("provider metadata requires id, displayName and version")
		}
	}
	compatible := false
	for _, v := range m.Spec.Protocol.Versions {
		if v == "0.1" {
			compatible = true
		}
	}
	if !compatible {
		return fmt.Errorf("provider does not support protocol 0.1")
	}
	switch m.Spec.Type {
	case "APPLICATION", "DATA", "AGENT", "DEVICE", "COMPOSITE":
	default:
		return fmt.Errorf("unsupported provider type")
	}
	for _, values := range [][]string{m.Spec.Protocol.Versions, m.Spec.Authority.Domains, m.Spec.Authentication.Schemes} {
		if len(values) == 0 {
			return fmt.Errorf("versions, domains and authentication schemes must not be empty")
		}
		seen := map[string]bool{}
		for _, value := range values {
			if strings.TrimSpace(value) == "" || seen[value] {
				return fmt.Errorf("manifest lists require unique nonempty entries")
			}
			seen[value] = true
		}
	}
	for _, e := range []Endpoint{m.Spec.Discovery.Resources, m.Spec.Discovery.Capabilities, m.Spec.Discovery.Schemas, m.Spec.Health} {
		u, err := url.Parse(e.Href)
		if err != nil || strings.ContainsAny(e.Href, " \t\r\n") {
			return fmt.Errorf("invalid endpoint")
		}
		relative := strings.HasPrefix(e.Href, "/") && !strings.HasPrefix(e.Href, "//") && u.Host == "" && u.Scheme == ""
		absolute := u.Scheme == "https" && u.Hostname() != "" && u.User == nil
		if !relative && !absolute {
			return fmt.Errorf("endpoint must be HTTPS or a root-relative path")
		}
	}
	return nil
}
