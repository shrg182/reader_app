"""User-facing HTTP error handling."""

from flask import Flask, render_template


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("errors/error.html", code=400, title="Invalid request",
                               message="The request could not be validated. Please try again."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/error.html", code=403, title="Access denied",
                               message="You do not have permission to access this resource."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="The requested page or book could not be found."), 404

    @app.errorhandler(413)
    def too_large(_error):
        return render_template("errors/error.html", code=413, title="Upload too large",
                               message="The uploaded file exceeds the supported size limit."), 413

    @app.errorhandler(500)
    def internal_error(_error):
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               message="Reader could not complete the request."), 500
