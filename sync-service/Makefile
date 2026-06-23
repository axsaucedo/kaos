IMG ?= axsauze/kaos-sync:dev

.PHONY: help build test vet lint docker-build clean

help:
	@echo "KAOS sync service targets:"
	@echo "  build        - Compile the kaos-sync binary into bin/"
	@echo "  test         - Run unit tests"
	@echo "  vet          - Run go vet"
	@echo "  lint         - Run gofmt check and go vet"
	@echo "  docker-build - Build the container image (IMG=$(IMG))"

build:
	go build -o bin/kaos-sync ./cmd

test:
	go test ./... -v

vet:
	go vet ./...

lint: vet
	@test -z "$$(gofmt -l cmd internal)" || (echo "gofmt needed on:" && gofmt -l cmd internal && exit 1)

docker-build:
	docker build -t $(IMG) .

clean:
	rm -rf bin
