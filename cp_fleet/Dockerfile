FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY call_put_fleet.py .
CMD ["python", "-u", "call_put_fleet.py"]
