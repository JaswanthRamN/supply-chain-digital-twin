.PHONY: dev test lint install

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload

dashboard:
	streamlit run dashboard/control_tower.py

test:
	pytest -q

lint:
	ruff check .
