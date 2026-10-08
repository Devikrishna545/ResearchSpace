PYTHON ?= python
BACKEND := backend
install:
	cd $(BACKEND) && $(PYTHON) -m pip install -e .
migrate:
	cd $(BACKEND) && $(PYTHON) -m scripts.migrate
run:
	$(PYTHON) app.py
test:
	cd $(BACKEND) && $(PYTHON) -m pytest
lint:
	cd $(BACKEND) && $(PYTHON) -m compileall app tests
up:
	docker compose up -d
down:
	docker compose down
