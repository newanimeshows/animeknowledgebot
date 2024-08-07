from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello, this is the Flask app!'

@app.route('/health')
def health_check():
    return 'Healthy', 200
