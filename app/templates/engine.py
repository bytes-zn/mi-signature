"""Jinja2 template engine with sandboxing and strict variable validation.

Templates may only reference variables from the canonical user contract
(:class:`app.core.user_context.UserContext`). Validation happens at save
time, so a template that references data the Graph sync can never deliver
is rejected before it is stored.

Security: templates are rendered in Jinja2's sandboxed environment, which
blocks attribute access to unsafe internals (``__class__`` etc.). Globals
that allow unbounded computation (``range``, ``lipsum``) are removed - the
rendering happens synchronously in the mail path, so a template that loops
millions of times would block the worker for every incoming message.
"""

import re
from typing import Any

from jinja2 import Template, meta
from jinja2.exceptions import SecurityError, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from app.core.exceptions import ValidationError
from app.core.user_context import KNOWN_USER_VARIABLES, UserContext

#: Maximum size of a rendered template in characters.
MAX_RENDER_LENGTH = 200_000

#: Number of compiled templates kept in memory.
TEMPLATE_CACHE_SIZE = 256


def _filter_initials(value: Any) -> str:
    """Return the initials of a name: ``"John Doe" -> "JD"``."""
    if not value:
        return ""
    return "".join(part[0] for part in str(value).split() if part).upper()


def _filter_tel(value: Any) -> str:
    """Normalize a phone number for ``tel:`` links (keeps leading ``+``)."""
    if not value:
        return ""
    cleaned = re.sub(r"[\s\-()/]", "", str(value))
    return cleaned


def create_environment() -> SandboxedEnvironment:
    """Build the sandboxed Jinja2 environment with custom filters."""
    env = SandboxedEnvironment(autoescape=False)
    env.filters["initials"] = _filter_initials
    env.filters["tel"] = _filter_tel
    # Remove globals that allow unbounded computation.
    for name in ("range", "lipsum"):
        env.globals.pop(name, None)
    return env


class TemplateEngine:
    """Validates and renders signature templates.

    Compiled templates are cached: the signature is rendered for every
    incoming mail, and re-parsing the template source every time would
    dominate the processing time.
    """

    def __init__(self) -> None:
        self._env = create_environment()
        self._cache: dict[str, Template] = {}

    def validate(self, source: str) -> None:
        """Validate template syntax and variables.

        Raises:
            ValidationError: on syntax errors or unknown variables.
        """
        try:
            ast = self._env.parse(source)
        except TemplateSyntaxError as exc:
            raise ValidationError(
                f"Template syntax error at line {exc.lineno}: {exc.message}"
            ) from exc

        unknown = meta.find_undeclared_variables(ast) - KNOWN_USER_VARIABLES
        if unknown:
            known = ", ".join(sorted(KNOWN_USER_VARIABLES))
            raise ValidationError(
                f"Unknown template variables: {', '.join(sorted(unknown))}. "
                f"Known variables: {known}.",
                code="unknown_template_variables",
            )

    def _compiled(self, source: str) -> Template:
        """Return the compiled template, validating it on the first use."""
        template = self._cache.get(source)
        if template is not None:
            return template

        self.validate(source)
        template = self._env.from_string(source)
        if len(self._cache) >= TEMPLATE_CACHE_SIZE:
            self._cache.clear()
        self._cache[source] = template
        return template

    def render(self, source: str, user: UserContext) -> str:
        """Render a template with the given user context.

        Raises:
            ValidationError: on syntax errors, unknown variables or
                sandbox security violations.
        """
        template = self._compiled(source)
        try:
            rendered = template.render(**user.model_dump())
        except SecurityError as exc:
            raise ValidationError(
                f"Template uses unsafe constructs: {exc}", code="unsafe_template"
            ) from exc
        if len(rendered) > MAX_RENDER_LENGTH:
            raise ValidationError(
                f"Rendered template exceeds the maximum size of {MAX_RENDER_LENGTH} characters.",
                code="template_too_long",
            )
        return rendered


_engine: TemplateEngine | None = None


def get_template_engine() -> TemplateEngine:
    """Return the process-wide template engine instance."""
    global _engine
    if _engine is None:
        _engine = TemplateEngine()
    return _engine
