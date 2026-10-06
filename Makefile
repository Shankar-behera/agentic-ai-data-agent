.PHONY: install lint type test seed run up down
install: ; pip install -e ".[dev]"
lint:    ; ruff check src tests
type:    ; mypy src
test:    ; pytest --cov=src
seed:    ; scripts/load_local.sh
run:     ; python -m src.main
up:      ; docker compose up --build -d
down:    ; docker compose down
