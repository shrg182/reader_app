"""Registration and session routes."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_

from reader_app.extensions import db
from reader_app.models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if current_user.is_authenticated:
        return redirect(url_for("library.index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if len(username) < 2:
            error = "Username must contain at least two characters."
        elif "@" not in email:
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must contain at least eight characters."
        elif db.session.scalar(
            db.select(User).where(or_(User.username == username, User.email == email))
        ):
            error = "That username or email is already registered."
        if error:
            flash(error, "error")
        else:
            user = User(username=username, email=email, password_hash="")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("library.index"))
    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if current_user.is_authenticated:
        return redirect(url_for("library.index"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        user = db.session.scalar(
            db.select(User).where(or_(User.username == identity, User.email == identity.lower()))
        )
        if user is None or not user.check_password(password):
            flash("Incorrect username/email or password.", "error")
        else:
            login_user(user)
            return redirect(url_for("library.index"))
    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
