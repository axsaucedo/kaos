# Build stage
FROM golang:1.24-alpine AS builder

WORKDIR /workspace

# Copy go files
COPY go.mod go.mod
COPY go.sum go.sum

# Copy the go source
COPY main.go main.go
COPY api/ api/
COPY controllers/ controllers/
COPY pkg/ pkg/

# Build
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -a -ldflags "-X main.GitVersion=dev" -o manager main.go

# Final stage
FROM gcr.io/distroless/static:nonroot
WORKDIR /

COPY --from=builder /workspace/manager .
USER 65532:65532

ENTRYPOINT ["/manager"]
