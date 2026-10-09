# senaite.pfas report scanner. Internal network only.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt licence_check.py ./
RUN pip install --no-cache-dir -r requirements.txt && python licence_check.py
COPY server.py ./
RUN useradd --system --uid 10001 scan
USER scan
EXPOSE 3001
CMD ["python", "server.py"]
