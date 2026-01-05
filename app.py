from flask import Flask, render_template
from scanner import scan

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html", data=scan())
