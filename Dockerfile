# The illustrative market-coupling back-test, reproducible with one command:
#   docker compose run --rm backtest
# Standard library only; the input snapshot is in data/.
FROM python:3.12-slim
WORKDIR /app
COPY backtest.py ./
COPY data ./data
ENTRYPOINT ["python", "backtest.py", "--data", "data", "--out", "/out"]
