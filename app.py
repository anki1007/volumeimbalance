# app.py

from flask import Flask, render_template
from scanner import scan

app = Flask(__name__)

@app.route("/")
def index():
    data = scan()
    return render_template("index.html", data=data)

if __name__ == "__main__":
    app.run(debug=True)
