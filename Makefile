.PHONY: api agent frontend test

api:
	uvicorn voicedesk.api:app --host 127.0.0.1 --port 8000

agent:
	python -m voicedesk.agent dev

frontend:
	cd frontend && npm run dev

test:
	python -m pytest
