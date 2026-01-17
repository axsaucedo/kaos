# Build stage
FROM golang:1.24-alpine AS builder

WORKDIR /workspace

# Copy go mod files first for better layer caching
COPY go.mod go.sum ./

# Download dependencies - this layer is cached unless go.mod/go.sum change
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# Copy the go source
COPY main.go main.go
COPY api/ api/
COPY controllers/ controllers/
COPY pkg/ pkg/

# Build with cache mount for faster rebuilds
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -a -ldflags "-X main.GitVersion=dev" -o manager main.go

# Final stage
FROM gcr.io/distroless/static:nonroot
WORKDIR /

COPY --from=builder /workspace/manager .
USER 65532:65532

ENTRYPOINT ["/manager"]
