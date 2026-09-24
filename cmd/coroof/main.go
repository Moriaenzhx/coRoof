// Copyright 2026 coRoof contributors
// SPDX-License-Identifier: AGPL-3.0-only

package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/SolanZhang/coRoof/internal/server"
	"github.com/SolanZhang/coRoof/pkg/contract"
	"github.com/SolanZhang/coRoof/pkg/provider"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		log.Print(err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: coroof serve [-addr 127.0.0.1:8080] | validate-provider FILE | roundtrip-work FILE | version")
	}
	switch args[0] {
	case "version":
		fmt.Println(server.Version)
		return nil
	case "validate-provider":
		if len(args) != 2 {
			return fmt.Errorf("usage: coroof validate-provider FILE")
		}
		f, err := os.Open(args[1])
		if err != nil {
			return err
		}
		defer f.Close()
		m, err := provider.Decode(f)
		if err != nil {
			return err
		}
		fmt.Printf("Provider %s: valid bootstrap manifest, protocol 0.1 (not registered or authorized)\n", m.Metadata.ID)
		return nil
	case "roundtrip-work":
		// Development utility for cross-language serialization tests; not an ingress API.
		if len(args) != 2 {
			return fmt.Errorf("usage: coroof roundtrip-work FILE")
		}
		b, err := os.ReadFile(args[1])
		if err != nil {
			return err
		}
		var work contract.WorkExperienceContract
		if err := json.Unmarshal(b, &work); err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(work)
	case "serve":
		flags := flag.NewFlagSet("serve", flag.ContinueOnError)
		addr := flags.String("addr", "127.0.0.1:8080", "HTTP listen address")
		if err := flags.Parse(args[1:]); err != nil {
			return err
		}
		if flags.NArg() != 0 {
			return fmt.Errorf("unexpected serve arguments")
		}
		return serve(*addr)
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func serve(addr string) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	srv := &http.Server{Addr: addr, Handler: server.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	result := make(chan error, 1)
	go func() { log.Printf("coRoof %s listening on %s", server.Version, addr); result <- srv.ListenAndServe() }()
	select {
	case err := <-result:
		return err
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := srv.Shutdown(shutdown); err != nil {
			return err
		}
		err := <-result
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}
