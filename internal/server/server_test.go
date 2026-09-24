// Copyright 2026 coRoof contributors
// SPDX-License-Identifier: AGPL-3.0-only

package server

import (
	"net/http/httptest"
	"testing"
)

func TestHTTPBoundary(t *testing.T) {
	for _, c := range []struct {
		method, path string
		want         int
	}{
		{"GET", "/healthz", 200}, {"GET", "/version", 200},
		{"POST", "/healthz", 405}, {"POST", "/actions", 404}, {"GET", "/healthz/unknown", 404},
	} {
		w := httptest.NewRecorder()
		Handler().ServeHTTP(w, httptest.NewRequest(c.method, c.path, nil))
		if w.Code != c.want {
			t.Errorf("%s %s = %d; want %d", c.method, c.path, w.Code, c.want)
		}
	}
}
