FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY even_odd_millipede.py .
CMD ["python", "-u", "even_odd_millipede.py"]
