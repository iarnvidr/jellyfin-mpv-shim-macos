package main

import (
	"context"
	"fmt"

	"dagger/check/internal/dagger"
)

type Jellyfin struct{}

const (
	pythonImage = "python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d"
	uvImage     = "ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336"
)

// Checks runs the locked Linux integration and unit suites in the project's Python environment.
func (m *Jellyfin) Checks(ctx context.Context, source *dagger.Directory) (string, error) {
	uv := dag.Container().From(uvImage)
	c := dag.Container().From(pythonImage).
		WithFile("/usr/local/bin/uv", uv.File("/uv")).
		WithFile("/usr/local/bin/uvx", uv.File("/uvx")).
		WithExec([]string{"sh", "-ec", "apt-get update && apt-get install -y --no-install-recommends bash git build-essential pkg-config libffi-dev libssl-dev libmpv-dev ffmpeg && rm -rf /var/lib/apt/lists/*"}).
		WithDirectory("/src", source).WithWorkdir("/src").
		WithExec([]string{"uv", "python", "install"}).
		WithExec([]string{"python", "scripts/prepare.py"}).
		WithExec([]string{"sh", "-ec", "before=$(sha256sum uv.lock | cut -d ' ' -f1); uv sync --locked --all-groups; after=$(sha256sum uv.lock | cut -d ' ' -f1); test \"$before\" = \"$after\""}).
		WithExec([]string{"uv", "run", "--locked", "python", "scripts/check.py"}).
		WithExec([]string{"uv", "run", "--locked", "python", "-m", "unittest", "discover", "-s", "tests", "-q"})
	text, err := c.Stdout(ctx)
	if err != nil {
		return "", fmt.Errorf("Jellyfin integration checks: %w", err)
	}
	return text, nil
}
