SHELL := /bin/sh
COMPOSE := docker compose

.PHONY: build up test ingest train

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d postgres qdrant label-studio dashboard-backend dashboard-frontend

test:
	$(COMPOSE) run --rm dashboard-backend pytest -q

ingest:
	$(COMPOSE) run --rm ingestion python -m ingestion.main

train:
	$(COMPOSE) run --rm detection python -m detection.train
